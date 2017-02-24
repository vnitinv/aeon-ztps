FROM phusion/baseimage:0.9.19
MAINTAINER community@apstra.com

RUN apt-get update

# xinetd \
# tftpd \
# tftp \

RUN apt-get install -y isc-dhcp-server \

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
    tree \
    sshpass

RUN apt-get -y install tftpd-hpa

RUN pip install --upgrade pip setuptools aeon-venos netaddr ansible

# install Dir : /opt/aeonztps

###########################################
## Create Directory
###########################################
RUN useradd -M -rs /bin/bash aeon


RUN mkdir /opt/aeonztps \
          /opt/aeonztps/logs \
          /opt/aeonztps/run \
          /opt/aeonztps/packages \
          /opt/aeonztps/src

RUN chown -R aeon:aeon /opt/aeonztps &&\
    chmod -R 755 /opt/aeonztps

COPY  bin /opt/aeonztps/bin
COPY  etc /opt/aeonztps/etc
COPY  vendor_images /opt/aeonztps/vendor_images
COPY  downloads /opt/aeonztps/downloads
COPY  docs /opt/aeonztps/docs

COPY  aeon_ztp /opt/aeonztps/src/aeon_ztp
COPY  setup.py  /opt/aeonztps/src
COPY  MANIFEST.in /opt/aeonztps/src
COPY  requirements.txt /opt/aeonztps/src

RUN chmod +x /opt/aeonztps/bin/* &&\
    chmod -R g+w /opt/aeonztps/vendor_images &&\
    chmod -R g+w /opt/aeonztps/docs &&\
    chmod -R g+w /opt/aeonztps/downloads

RUN mkdir /var/run/aeon-ztp /var/log/aeon-ztp
RUN chown -R aeon:aeon /var/run/aeon-ztp &&\
    chown -R aeon:aeon /var/log/aeon-ztp &&\
    chmod -R 777 /var/log/aeon-ztp  &&\
    chmod -R 777 /var/run/aeon-ztp

COPY ztp-scripts /opt/aeonztps/tftpboot
RUN  chmod -R 777 /opt/aeonztps/tftpboot

RUN ln -s /opt/aeonztps/tftpboot/ztp-cumulus.sh /opt/aeonztps/downloads/ztp-cumulus.sh
RUN ln -s /opt/aeonztps/bin/aztp-db-flush /usr/local/bin/aztp-db-flush

WORKDIR /opt/aeonztps/src
RUN python setup.py install


WORKDIR /opt/aeonztps/docs
RUN make html

RUN rm -rf /opt/aeonztps/src
###########################################
## install TFTP
###########################################
COPY docker/tftp/config /etc/xinetd.d/tftp


##########################################
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


CMD ["/sbin/my_init"]
