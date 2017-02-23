FROM phusion/baseimage:0.9.19
MAINTAINER community@apstra.com

RUN apt-get update

RUN apt-get install -y isc-dhcp-server \
    xinetd \
    tftpd \
    tftp \
    rabbitmq-server \
    libfcgi \
    nginx-full \
    uwsgi \
    uwsgi-plugin-python \
    build-essential \
    python-dev \
    python-pip \
    libyaml-dev \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    rsync \
    vim \
    tree

RUN pip install --upgrade pip setuptools aeon-venos netaddr

###########################################
## install TFTP
###########################################
COPY docker/tftp/config /etc/xinetd.d/tftp




## Install WebServer
###########################################
COPY docker/webserver/uwsgi.aeon-ztp.ini /etc/uwsgi/apps-available/aeon-ztp.ini
RUN ln -s /etc/uwsgi/apps-available/aeon-ztp.ini /etc/uwsgi/apps-enabled/aeon-ztp.ini
COPY docker/webserver/default.ini /usr/share/uwsgi/conf/default.ini

COPY docker/webserver/nginx.conf /etc/nginx/nginx.conf
COPY docker/webserver/nginx.aeon-ztp.ini /etc/nginx/sites-enabled/aeon-ztp.ini
RUN rm -rf /etc/nginx/sites-enabled/default

COPY docker/webserver/celeryd.conf /etc/default/celeryd
COPY docker/webserver/run-nginx.sh /etc/service/nginx/run

RUN  chmod +x /etc/service/nginx/run

RUN mkdir /var/log/aeon-ztp
RUN useradd -M -rs /bin/bash aeon

CMD ["/sbin/my_init"]
