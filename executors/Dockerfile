FROM --platform=linux/amd64 archlinux@sha256:b21322c663be387c0ed9cbc7bbbfe18e41633ad4e7b7c77cfad45f128be20040

# A dated archive pins the complete OS dependency graph, including downgrades.
RUN printf 'Server = https://archive.archlinux.org/repos/2026/09/18/$repo/os/$arch\n' > /etc/pacman.d/mirrorlist \
    && pacman -Syyuu --noconfirm --needed base-devel python python-pip git ripgrep fish \
       bubblewrap cmake uv nodejs npm jre17-openjdk \
    && pacman -Scc --noconfirm

# Match the Rust toolchain used in the recorded host runs.
RUN curl -fsSLo /tmp/rust.tar.xz https://static.rust-lang.org/dist/rust-1.95.0-x86_64-unknown-linux-gnu.tar.xz \
    && echo '2e0338f18ecbaa4a0f631b9e80e8b8e26bb6fe77dd5454fba8a70cf96c1e84a1  /tmp/rust.tar.xz' | sha256sum -c - \
    && tar -xJf /tmp/rust.tar.xz -C /tmp \
    && /tmp/rust-1.95.0-x86_64-unknown-linux-gnu/install.sh --prefix=/usr/local \
       --components=rustc,cargo,rust-std-x86_64-unknown-linux-gnu --disable-ldconfig \
    && rm -rf /tmp/rust*

WORKDIR /opt/agent-lab/harnesses
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund && npm cache clean --force

# Quality-checker dependencies stay out of the agent's default Python.
COPY requirements.lock /tmp/requirements.lock
RUN uv venv --python /usr/bin/python3 /opt/agent-lab/quality \
    && uv pip install --python /opt/agent-lab/quality/bin/python --require-hashes -r /tmp/requirements.lock \
    && ln -s /opt/agent-lab/quality/bin/scb-check /usr/local/bin/scb-check \
    && rm /tmp/requirements.lock \
    && mkdir -p /opt/agent-lab/runner /home/agent \
       /opt/agent-lab/provider-config/codex /opt/agent-lab/provider-config/pi \
    && chmod 1777 /home/agent /opt/agent-lab/runner \
    && git config --system user.name 'Agent Behavior Lab' \
    && git config --system user.email 'lab@example.invalid'

ENV HOME=/home/agent USER=agent SHELL=/usr/bin/fish LANG=C.UTF-8 LC_ALL=C.UTF-8
ENV PATH=/opt/agent-lab/harnesses/node_modules/.bin:/usr/local/bin:/usr/bin:/usr/lib/jvm/default/bin
WORKDIR /opt/agent-lab/runner
