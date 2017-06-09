import requests
import cherrypy
import json
import glob
from itertools import groupby
from bs4 import BeautifulSoup

class FactChecker(object):
    data_cache = []
    label_cache = {}

    def label_for(self, q):
        cherrypy.log(f"labeling {q}")
        q = q.upper()
        if q in self.label_cache:
            return self.label_cache[q]
        url = 'https://www.wikidata.org/w/api.php?action=wbgetentities&props=labels&ids=%s&languages=en&format=json' % q
        resp = requests.get(url)
        v = resp.json()['entities'][q]['labels']['en']['value']
        self.label_cache[q] = v
        return v

    def link_for(self, q):
        return f"https://www.wikidata.org/wiki/{q}"

    def wiki_link_for(self, name):
        name_quoted = name.replace(" ", "_")
        return f"https://en.wikipedia.org/wiki/{name_quoted}"

    def chunk_text(self, text, chunks):
        if not text:
            return chunks
        else:
            chunk = ".".join(text.split(".")[:5]) + "."
            rest = ".".join(text.split(".")[5:])
            return chunk_text(rest, chunks + [chunk])

    def get_relations(self, page):
        soup = BeautifulSoup(page, 'html.parser')
        page = "\n".join([p.getText().strip() for p in soup.find_all('p')])
        chunks = self.chunk_text(page)
        relations = []
        for chunk in chunks:
            resp = requests.post('http://localhost:8080/api/en/extract', data=chunk)
            if resp.status_code == 200:
                relations.append(resp.json())
            else:
                return (resp.status_code, resp.text)
        return (200, relations)

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
                page = requests.get(url).text
            except requests.exceptions.RequestException as e:
                cherrypy.log(f"Could not get url: {url}")
                cherrypy.response.status = '503'
                return f"Could not get the requested url: {url}"

            # Connect to Prometheus
            cherrypy.log("Extracting relations from Prometheus...")
            try:
                relations = self.get_relations(page)
                if relations[0] != 200:
                    cherrypy.log(f"Bad response from Prometheus: {relations[1]}")
                    cherrypy.response.status = '503'
                    return f"Bad response from Prometheus {relations[1]}"
                else:
                    relations = relations[1]

                cherrypy.log("relations extracted: %s" % relations)
            except:
                cherrypy.log("An error ocurred while connecting to Prometheus")
                cherrypy.response.status = '503'
                return "An error occurred while connecting to Prometheus"

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
                cherrypy.log("tampering with evidence")
                for match in evidence[1]:
                    match['subject'] = self.label_for(match['subject'])
                    match['predictedPredicate'] = self.label_for(match['predictedPredicate'])
                    match['obj'] = self.label_for(match['obj'])
                result['evidence'] = list(map(lambda e: self.trim_evidence(e), evidence[1]))
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
            'link': self.wiki_link_for(self.label_for(name))
        }


    def check_relation(self, relation):
        sub = relation['subject']
        obj = relation['obj']
        pred = relation['predictedPredicate']

        if not self.data_cache:
            # read data
            files = glob.glob("extractions/part-*")
            for path in files:
                with open(path) as file:
                    lines = file.readlines()
                    self.data_cache.extend([json.loads(l) for l in lines])
        matches = [match for match in self.data_cache if match['predictedPredicate'] == pred and match['subject'] == sub]

        if len(matches) == 0:
            return ("unknown", [])

        for match in matches:
            if match['obj'] == obj:
                # found one match, the relation is considered True
                return ("verified", [match])

        return ("conflicting", matches)

if __name__ == "__main__":
    cherrypy.config.update(
            {'server.socket_port': 8081} )
    cherrypy.quickstart(FactChecker())
