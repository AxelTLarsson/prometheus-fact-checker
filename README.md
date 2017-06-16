# Prometheus Fact Checker
*Check website facts against Prometheus Relation Extractor/Model*

This program creates a simple REST api that listens to 0.0.0.0:8081/check for POST requests containing an `url` parameter. If present the program will fetch the url, extract the plain text and send it to the Prometheus Relation Extractor to get back relation triples.

These triples will be checked against a local database of extractions `extractions/` in the Prometheus extraction format.

This application acts as the backend for the [Prometheus Chrome plugin](https://github.com/ErikGartner/prometheus-chrome-plugin).

## Usage/Installation
Just install the dependencies in `requirements.txt` and put the database in `extractions/`.

This is done automatically by our Docker image, run it using the following commands:

```bash
docker build -t prometheus/fact_checker:latest .
docker run -p 8081:8081 -t prometheus/fact_checker:latest
```
