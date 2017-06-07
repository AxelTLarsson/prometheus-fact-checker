import requests as r
import cherrypy
import json


class FactChecker(object):
    @cherrypy.expose
    def index(self):
        return "POST with URL to /check to do fact checking"

    @cherrypy.expose
    def check(self, url=None):
        if url is not None:
            print("GET %s..." % url)
            try:
                page = r.get(url)
            except:
                print("Could not get url")
                cherrypy.response.status = '503'
                return "Could not get the requested url"

            print("Extracting relations from Prometheus...")

            try:
                #  relations = r.post('http://localhost:9000/api/en/extract', data=page).json()
                relations = json.dumps([
                    {
                        'subject': 'Q76',
                        'predictedPredicate': 'P26',
                        'obj': 'Q13133',
                        'sentence': 'bla bla',
                        'source': 'eh',
                        'probability': '0.99'
                    }])
                print("relations extracted: %s" % relations)
                return relations
            except ConnectionError as e:
                print("An error ocurred while connecting to Prometheus")
                cherrypy.response.status = '503'
                return "An error occurred while connecting to Prometheus"


        return "all is well and the url is: " + str(url)


if __name__ == "__main__":
    cherrypy.quickstart(FactChecker())
