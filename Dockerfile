FROM apache/airflow:3.3.0-python3.12

USER root

# System deps some Python packages need to build (e.g. cryptography, duckdb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && apt-get autoremove -yqq --purge \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Install project dependencies into the airflow user's environment
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt
