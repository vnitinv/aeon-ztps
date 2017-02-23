

build:
	docker build -t apstra/aeon-ztps .

cli:
	docker run -i -t apstra/aeon-ztps bash

start:
	docker run -d --rm -p 8080:8080 -p 80:80 apstra/aeon-ztps
