# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install Prometheus client and any XML/http libs
RUN pip install prometheus_client 

COPY artnet-exporter.py .

EXPOSE 9288 

CMD ["python", "artnet-exporter.py"]
