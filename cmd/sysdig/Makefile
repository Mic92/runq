all: sysdig

image:
	docker build -t sysdig-static .

sysdig: image
	docker run --rm sysdig-static cat /src/build/userspace/sysdig/sysdig > sysdig
	chmod +x sysdig
