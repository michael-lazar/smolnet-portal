FROM --platform=linux/amd64 archlinux

RUN pacman -Syu --noconfirm base-devel git imake unzip openmotif

RUN useradd -m aurbuilder
USER aurbuilder
WORKDIR /home/aurbuilder

RUN git clone https://aur.archlinux.org/gophervr.git && \
    cd gophervr && makepkg -s

USER root
RUN pacman -U --noconfirm /home/aurbuilder/gophervr/*.pkg.tar.zst

CMD ["/usr/sbin/gophervr"]
