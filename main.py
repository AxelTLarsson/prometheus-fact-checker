import requests
from requests_futures.sessions import FuturesSession
import concurrent
from concurrent.futures import ALL_COMPLETED
import cherrypy
import json
import glob
from itertools import groupby
from bs4 import BeautifulSoup
import copy
from functools import partial

CHUNK_SIZE = 10 # Number of paragraphs in a chunk
PARALLEL_REQUESTS = 10
PROMETHEUS_URL = 'http://localhost:8080/api/en/extract'
PROMETHEUS_TIMEOUT = 120 # Maximum number of seconds to wait for Prometheus for one page extraction

class FactChecker(object):

    def __init__(self):
        self.data_cache = []
        self.label_cache = {}

    def label_for(self, q):
        q = q.upper()
        if q in self.label_cache:
            return self.label_cache[q]
        cherrypy.log(f"Resolving name for {q}")
        url = 'https://www.wikidata.org/w/api.php?action=wbgetentities&props=labels&ids=%s&languages=en&format=json' % q
        resp = requests.get(url)
        try:
            v = resp.json()['entities'][q]['labels']['en']['value']
            self.label_cache[q] = v
        except Exception as e:
            cherrypy.log(f"Could not resolve name for {q}")
            v = "unknown"
        return v

    def link_for(self, q):
        return f"https://www.wikidata.org/wiki/{q}"

    def wiki_link_for(self, name):
        name_quoted = name.replace(" ", "_")
        return f"https://en.wikipedia.org/wiki/{name_quoted}"

    def chunk_text(self, text, chunks = []):
        if not text:
            return chunks
        else:
            chunk = ".".join(text.split(".")[:5]) + "."
            rest = ".".join(text.split(".")[5:])
            return self.chunk_text(rest, chunks + [chunk])

    # Get a list of extracted relations from Prometheus for "page"
    # The page is chunked by CHUNK_SIZE number of paragraphs and sent up to PARALLEL_REQUESTS in parallel
    # If any of those requests fails, it will be logged but no further action will be taken
    # The return value is a list of relations
    def get_relations(self, page):
        soup = BeautifulSoup(page, 'html.parser')

        # Chunking
        paragraphs = [p.getText().strip() for p in soup.find_all('p')]
        paragraphs = [c for c in paragraphs if c != '']
        chunks = []
        for i in range(0, len(paragraphs), CHUNK_SIZE):
            chunks.append('. '.join(paragraphs[i:i+CHUNK_SIZE]))

        session = FuturesSession(max_workers=PARALLEL_REQUESTS)
        fs = []

        # Send concurrent requests to extract chunks
        if not chunks:
            cherrypy.log("No text in page")
        for chunk in chunks:
            resp = session.post(
                    PROMETHEUS_URL,
                    data=chunk.encode('UTF-8'),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                        },
                    timeout=60)
            fs.append(resp)
            cherrypy.log("Sent chunk for extraction")

            # Print some info when responses complete
            def response_completed_callback(data, f):
                cherrypy.log("An extraction request completed")
                try:
                    res = f.result()
                    if res.status_code != 200:
                        cherrypy.log("HTTP Status Code NOK!")
                        cherrypy.log("Original data was")
                        cherrypy.log(data)

                except Exception as e:
                    cherrypy.log(f"Raised exception")
                    cherrypy.log("Original data was:")
                    cherrypy.log(data)

            resp.add_done_callback(partial(response_completed_callback, chunk))

        # Await completion of all reponses
        try:
            cherrypy.log(f"Waiting up to {PROMETHEUS_TIMEOUT} s for all extraction requests to complete...")
            (done, not_done) = concurrent.futures.wait(fs, timeout=PROMETHEUS_TIMEOUT, return_when=ALL_COMPLETED)
            fs = done
            cherrypy.log("Done")
        except Exception as e:
            cherrypy.log("Some requests did not finish within {PROMETHEUS_TIMEOUT} s.")
            for f in not_done:
                f.cancel()



        relations = []
        for f in fs:
            try:
                # Low timeout because above wait should have ensured all were completed
                resp = f.result(timeout=0.001)
                if resp.status_code == 200:
                    relations.append(resp.json())
                else:
                    cherrypy.log(f"Response: {resp.status_code} {resp.text}")
            except Exception as e:
                cherrypy.log(f"Request failed: {e}")

        return self.flatten(relations)

    def flatten(self, the_list):
        return [val for sublist in the_list for val in sublist]


    @cherrypy.expose
    def index(self):
        return "POST with URL to /check to do fact checking"

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def check(self, url=None):
        if url is not None:
            # GET the page
            cherrypy.log(f"GET {url}")
            try:
                page = requests.get(url, timeout=10).text
            except Exception as e:
                cherrypy.log(f"Could not get url: {url}: {e}")
                cherrypy.response.status = '503'
                return f"Could not get the requested url: {url}"

            # Connect to Prometheus
            cherrypy.log("Extracting relations from Prometheus...")
            relations = self.get_relations(page)

            # Group extracted relations by relation triple
            def keyfunc(relation):
                return (relation['subject'], relation['predictedPredicate'], relation['obj'])

            extractions = []
            data = sorted(relations, key=keyfunc)
            for k, g in groupby(data, keyfunc):
                extractions.append(list(g))      # Store group iterator as a list
            results = []
            for extraction in extractions:
                # only check once per actual relation
                evidence = self.check_relation(extraction[0])
                result = {}
                result['subject'] = {
                    'name': self.label_for(extraction[0]['subject']),
                    'link': self.link_for(extraction[0]['subject'])
                }
                result['object'] = {
                    'name': self.label_for(extraction[0]['obj']),
                    'link': self.link_for(extraction[0]['obj'])
                }
                result['predicate'] = {
                    'name': self.label_for(extraction[0]['predictedPredicate']),
                    'link': self.link_for(extraction[0]['predictedPredicate'])
                }
                result['sentences'] = list(map(lambda r: r['sentence'], extraction))
                result['type'] = evidence[0]

                for match in evidence[1]:
                    match['subject'] = self.label_for(match['subject'])
                    match['predictedPredicate'] = self.label_for(match['predictedPredicate'])
                    match['obj'] = self.label_for(match['obj'])
                result['evidence'] = list(map(lambda e: self.trim_evidence(e), evidence[1]))
                result['probablity'] = extraction[0]['probability']
                results.append(result)

            return results

        else:
            cherrypy.response.status = '400'
            return "No URL to check supplied"

    def trim_evidence(self, evidence):
        name = evidence['source'].split(":")

        if len(name) == 3:
            name = name[2]
        else:
            name = ""

        return {
            'subject': evidence['subject'],
            'object': evidence['obj'],
            'predicate': evidence['predictedPredicate'],
            'snippet': evidence['sentence'],
            'link': self.wiki_link_for(self.label_for(name)),
            'source': 'Wikipedia',
            'probability': evidence['probability']
        }

    def check_relation(self, relation):
        sub = relation['subject']
        obj = relation['obj']
        pred = relation['predictedPredicate']

        if len(self.data_cache) == 0:
            # read data
            files = glob.glob("extractions/part-*")
            for path in files:
                with open(path) as file:
                    lines = file.readlines()
                    self.data_cache.extend([json.loads(l) for l in lines])

        matches = [match for match in self.data_cache if (match['subject'] == sub
                   and match['predictedPredicate'] == pred)]

        if len(matches) == 0:
            return ("unknown", [])

        for match in matches:
            if match['obj'] == obj:
                # found one match, the relation is considered True
                return ("verified", [copy.deepcopy(match)])

        return ("conflicting", copy.deepcopy(matches))

if __name__ == "__main__":
    cherrypy.config.update(
            {'server.socket_port': 8081,
             'server.socket_host': '0.0.0.0'})
    cherrypy.quickstart(FactChecker())
