FROM python:3.10.5
# FROM colesbury/python-nogil
WORKDIR /reinhard

COPY ./reinhard ./reinhard
COPY ./requirements.txt ./requirements.txt
COPY ./main.py ./main.py

# Only neccessary if pyjion is also being installed.
# RUN wget https://packages.microsoft.com/config/ubuntu/21.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb
# RUN dpkg -i packages-microsoft-prod.deb
# RUN rm packages-microsoft-prod.deb
# RUN apt-get update; \
#   apt-get install -y apt-transport-https && \
#   apt-get update && \
#   apt-get install -y aspnetcore-runtime-6.0

ARG debug=false
ENV DOCKER_DEBUG=${debug}
RUN python -m pip install --upgrade pip wheel
RUN python -m pip install -r requirements.txt
# RUN python -m pip install pyjion
ENV ALLUKA_RUST_PATCH="true"
ARG alluka_rust_hash
ARG rukari_hash

RUN if [ -n ${rukari_hash} ] || [ -n ${alluka_rust_hash} ]; then \
    curl https://sh.rustup.rs -sSf | bash -s -- -y; \
fi

RUN if [ -n ${alluka_rust_hash} ]; then \
    python -m pip install --force-reinstall --no-deps git+https://github.com/fasterspeeding/tanjun.git@task/alluka_rust && \
    export PATH="$HOME/.cargo/bin:$PATH" && \
    python -m pip install git+https://github.com/fasterspeeding/alluka_rust.git@${alluka_rust_hash}; \
fi

RUN if [ -n ${rukari_hash} ]; then \
    export PATH="$HOME/.cargo/bin:$PATH" && \
    python -m pip install git+https://github.com/FasterSpeeding/Rukari.git@${rukari_hash}; \
fi

ENTRYPOINT if ${DOCKER_DEBUG} == false; then python main.py; else python -OO main.py; fi
