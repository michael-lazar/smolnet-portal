# GopherVR

This is a simple docker setup that allows me to launch a
containerized instance of GopherVR on my m1 macbook air.

This uses the gopherVR package in the AUR: https://aur.archlinux.org/packages/gophervr

I had to setup XQuartz & X11 forwarding as described here: https://gist.github.com/sorny/969fe55d85c9b0035b0109a31cbcb088

To launch it, run

```shell
xhost +
docker-compose run gophervr
```
