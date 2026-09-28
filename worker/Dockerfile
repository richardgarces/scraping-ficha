FROM golang:1.21-alpine AS build
WORKDIR /src
COPY worker.go go.mod go.sum ./
RUN go build -o /bin/worker ./worker.go

FROM alpine:3.18
RUN apk add --no-cache ca-certificates
COPY --from=build /bin/worker /usr/local/bin/worker
ENV REDIS_URL=redis://redis:6379/0

# Añadir Python runtime y copiar el runner y el paquete scraping
RUN apk add --no-cache python3 py3-pip
COPY worker/runner.py /usr/local/bin/worker/runner.py
# Copiar todo el repo para que el paquete editable pueda instalarse
COPY .. /workspace
WORKDIR /workspace/scraping
# Instalar paquete en modo editable
RUN pip install --no-cache-dir -e . || true

# Instalar cliente HTTP ligero para llamadas a servicios externos
RUN pip install --no-cache-dir requests || true

# Directoria para utilidades adicionales
RUN mkdir -p /usr/local/lib/worker && true

ENTRYPOINT ["/usr/local/bin/worker"]

