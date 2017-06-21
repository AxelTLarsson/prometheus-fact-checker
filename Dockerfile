FROM python:3.6
LABEL maintainer "erikgartner@sony.com"

RUN mkdir /app
WORKDIR /app
COPY requirements.txt ./

RUN python -m pip install -r requirements.txt

COPY main.py ./

ENV DATABASE_URL "https://s3-eu-west-1.amazonaws.com/sony-prometheus-data/docker_data/extractions.tar.gz"
ADD $DATABASE_URL ./
RUN tar xvf extractions.tar.gz && rm -f extractions.tar.gz

EXPOSE 8081
VOLUME /extractions
CMD python main.py
