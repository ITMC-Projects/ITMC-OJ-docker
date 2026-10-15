FROM python:3.11-slim-bookworm

RUN apt-get update -o APT::Update::Error-Mode=any && \
    apt-get install -y \
        git gcc g++ make curl gettext wget \
        libxml2-dev libxslt1-dev zlib1g-dev \
        mariadb-client libmariadb-dev \
        libjpeg-dev debconf-utils pkg-config && \
    curl -fsSL https://deb.nodesource.com/setup_18.x -o /tmp/nodesource_setup.sh && \
    bash /tmp/nodesource_setup.sh && \
    rm /tmp/nodesource_setup.sh && \
    apt-get install -y nodejs && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /
COPY repo/requirements.txt .
COPY repo/additional_requirements.txt .
COPY repo/package.json .
COPY repo/package-lock.json .
RUN npm ci
# The application requires packaging<22; newer setuptools/wheel require a newer API.
RUN pip3 install setuptools==70.3.0 wheel==0.45.1 && \
    pip3 install -r requirements.txt
RUN pip3 install -r additional_requirements.txt && \
    pip3 install lxml_html_clean mysqlclient==2.1.1 websocket-client
