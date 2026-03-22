#!/usr/bin/env bash
# AiSE - AI Support Engineer System
# Installation script for Debian/Ubuntu and RHEL/CentOS/Fedora/Amazon Linux
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── OS detection ──────────────────────────────────────────────────────────────
detect_os() {
    [ -f /etc/os-release ] || error "Cannot detect OS: /etc/os-release not found."
    . /etc/os-release
    OS_ID="${ID}"
    OS_ID_LIKE="${ID_LIKE:-}"

    if echo "${OS_ID} ${OS_ID_LIKE}" | grep -qiE "debian|ubuntu|mint|pop|kali|raspbian"; then
        PKG_FAMILY="debian"
        PKG_UPDATE="apt-get update -qq"
        PKG_INSTALL="apt-get install -y"
    elif echo "${OS_ID} ${OS_ID_LIKE}" | grep -qiE "rhel|centos|fedora|amzn|rocky|almalinux|ol"; then
        PKG_FAMILY="rpm"
        if command -v dnf &>/dev/null; then
            PKG_UPDATE="dnf check-update -q || true"
            PKG_INSTALL="dnf install -y"
        else
            PKG_UPDATE="yum check-update -q || true"
            PKG_INSTALL="yum install -y"
        fi
    else
        error "Unsupported OS: ${OS_ID}. Only Debian/Ubuntu and RHEL/CentOS/Fedora families are supported."
    fi

    info "Detected OS: ${OS_ID} (${PKG_FAMILY} family)"
}

# ── Privilege check ───────────────────────────────────────────────────────────
check_root() {
    if [ "$EUID" -ne 0 ]; then
        command -v sudo &>/dev/null || error "Run as root or install sudo."
        SUDO="sudo"
    else
        SUDO=""
    fi
}

# ── Generate secure random password ──────────────────────────────────────────
gen_password() {
    python3 -c "import secrets, string; \
        chars = string.ascii_letters + string.digits; \
        print(''.join(secrets.choice(chars) for _ in range(32)))"
}

# ── System dependencies ───────────────────────────────────────────────────────
install_system_deps() {
    info "Updating package index..."
    $SUDO $PKG_UPDATE

    info "Installing system dependencies..."
    if [ "$PKG_FAMILY" = "debian" ]; then
        # Detect Ubuntu/Debian version to handle package name differences
        OS_VERSION_ID="${VERSION_ID:-}"
        OS_CODENAME="${VERSION_CODENAME:-$(lsb_release -cs 2>/dev/null || echo '')}"

        # Install base packages first
        $SUDO $PKG_INSTALL \
            curl wget git ca-certificates gnupg lsb-release \
            build-essential libssl-dev libffi-dev \
            python3-pip

        # Python 3.11 — available natively on Ubuntu 22.04/Debian 12+
        # On Ubuntu 24.04+ python3.11 may need deadsnakes PPA
        if apt-cache show python3.11 &>/dev/null 2>&1; then
            $SUDO $PKG_INSTALL python3.11 python3.11-dev python3.11-venv
        else
            info "python3.11 not in default repos — adding deadsnakes PPA..."
            $SUDO $PKG_INSTALL software-properties-common
            $SUDO add-apt-repository -y ppa:deadsnakes/ppa
            $SUDO apt-get update -qq
            $SUDO $PKG_INSTALL python3.11 python3.11-dev python3.11-venv
        fi

        # PostgreSQL client
        $SUDO $PKG_INSTALL postgresql-client redis-tools 2>/dev/null || \
            $SUDO $PKG_INSTALL postgresql-client 2>/dev/null || true

        # Playwright / browser dependencies — package names changed in Ubuntu 24.04
        PLAYWRIGHT_PKGS="libnss3 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1"

        # libatk renamed in Ubuntu 24.04
        if apt-cache show libatk1.0-0 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libatk1.0-0"
        elif apt-cache show libatk1.0-0t64 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libatk1.0-0t64"
        fi
        if apt-cache show libatk-bridge2.0-0 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libatk-bridge2.0-0"
        elif apt-cache show libatk-bridge2.0-0t64 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libatk-bridge2.0-0t64"
        fi

        # libcups2 renamed in Ubuntu 24.04
        if apt-cache show libcups2 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libcups2"
        elif apt-cache show libcups2t64 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libcups2t64"
        fi

        # libasound2 renamed in Ubuntu 24.04 (virtual package — must pick concrete one)
        if apt-cache show libasound2t64 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS libasound2t64"
        elif apt-cache show liboss4-salsa-asound2 2>/dev/null | grep -q "^Package:"; then
            PLAYWRIGHT_PKGS="$PLAYWRIGHT_PKGS liboss4-salsa-asound2"
        fi

        # shellcheck disable=SC2086
        $SUDO $PKG_INSTALL $PLAYWRIGHT_PKGS
    else
        if echo "${OS_ID}" | grep -qiE "centos|rhel|rocky|almalinux|ol"; then
            $SUDO $PKG_INSTALL epel-release 2>/dev/null || true
        fi
        $SUDO $PKG_INSTALL \
            curl wget git ca-certificates \
            gcc gcc-c++ make openssl-devel libffi-devel \
            python3.11 python3.11-devel \
            postgresql redis \
            nss atk at-spi2-atk cups-libs libdrm libxkbcommon \
            libXcomposite libXdamage libXfixes libXrandr mesa-libgbm alsa-lib
    fi
    success "System dependencies installed."
}

# ── Docker ────────────────────────────────────────────────────────────────────
install_docker() {
    if command -v docker &>/dev/null; then
        success "Docker already installed: $(docker --version)"
    else
        info "Installing Docker..."
        if [ "$PKG_FAMILY" = "debian" ]; then
            $SUDO install -m 0755 -d /etc/apt/keyrings
            curl -fsSL "https://download.docker.com/linux/${OS_ID}/gpg" \
                | $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${OS_ID} $(lsb_release -cs) stable" \
                | $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null
            $SUDO apt-get update -qq
            $SUDO $PKG_INSTALL docker-ce docker-ce-cli containerd.io docker-compose-plugin
        else
            $SUDO $PKG_INSTALL yum-utils 2>/dev/null || $SUDO $PKG_INSTALL dnf-plugins-core
            $SUDO yum-config-manager --add-repo \
                https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null \
                || $SUDO dnf config-manager --add-repo \
                https://download.docker.com/linux/centos/docker-ce.repo
            $SUDO $PKG_INSTALL docker-ce docker-ce-cli containerd.io docker-compose-plugin
        fi
        $SUDO systemctl enable --now docker
        success "Docker installed: $(docker --version)"
    fi

    # Add invoking user to docker group
    REAL_USER="${SUDO_USER:-${USER}}"
    if [ -n "$REAL_USER" ] && ! groups "$REAL_USER" 2>/dev/null | grep -q docker; then
        $SUDO usermod -aG docker "$REAL_USER"
        warn "User '${REAL_USER}' added to docker group — log out and back in for this to take effect."
    fi
}

# ── Poetry ────────────────────────────────────────────────────────────────────
install_poetry() {
    if command -v poetry &>/dev/null; then
        success "Poetry already installed: $(poetry --version)"
        return
    fi
    info "Installing Poetry..."
    curl -sSL https://install.python-poetry.org | python3 -
    export PATH="${HOME}/.local/bin:${PATH}"
    success "Poetry installed: $(poetry --version)"
}

# ── Generate .env with consistent credentials ─────────────────────────────────
setup_env() {
    if [ -f .env ]; then
        info ".env already exists — reading existing credentials."
        # Extract existing passwords so we don't overwrite them
        POSTGRES_PASS=$(grep -oP '(?<=postgresql://aise:)[^@]+' .env | head -1 || echo "")
        REDIS_PASS=$(grep -oP '(?<=redis://:)[^@]+' .env | head -1 || echo "")
        VAULT_KEY=$(grep -oP '(?<=CREDENTIAL_VAULT_KEY=)\S+' .env | head -1 || echo "")
        WEBHOOK_SECRET=$(grep -oP '(?<=WEBHOOK_SECRET=)\S+' .env | head -1 || echo "")
    else
        info "Creating .env from .env.example with generated credentials..."
        cp .env.example .env
        POSTGRES_PASS=""
        REDIS_PASS=""
        VAULT_KEY=""
        WEBHOOK_SECRET=""
    fi

    # Generate any missing secrets
    [ -z "$POSTGRES_PASS" ]   && POSTGRES_PASS=$(gen_password)
    [ -z "$REDIS_PASS" ]      && REDIS_PASS=$(gen_password)
    [ -z "$VAULT_KEY" ]       && VAULT_KEY=$(gen_password)
    [ -z "$WEBHOOK_SECRET" ]  && WEBHOOK_SECRET=$(gen_password)

    # Write all credential lines into .env (replace or append)
    set_env_var() {
        local key="$1" val="$2"
        if grep -q "^${key}=" .env 2>/dev/null; then
            sed -i "s|^${key}=.*|${key}=${val}|" .env
        else
            echo "${key}=${val}" >> .env
        fi
    }

    set_env_var "POSTGRES_URL"    "postgresql://aise:${POSTGRES_PASS}@localhost:5434/aise"
    set_env_var "DATABASE_URL"    "postgresql://aise:${POSTGRES_PASS}@localhost:5434/aise"
    set_env_var "REDIS_URL"       "redis://:${REDIS_PASS}@localhost:6380/0"
    set_env_var "CREDENTIAL_VAULT_KEY" "${VAULT_KEY}"
    set_env_var "WEBHOOK_SECRET"  "${WEBHOOK_SECRET}"
    set_env_var "CHROMA_HOST"     "localhost"
    set_env_var "CHROMA_PORT"     "8000"

    success ".env configured with generated credentials."
}

# ── Sync credentials into docker-compose.yml ─────────────────────────────────
sync_docker_compose() {
    info "Syncing credentials into docker-compose.yml..."

    # PostgreSQL password
    sed -i "s|POSTGRES_PASSWORD:.*|POSTGRES_PASSWORD: ${POSTGRES_PASS}|g" docker-compose.yml
    # PostgreSQL URLs in aise-api and aise-worker services
    sed -i "s|postgresql://aise:[^@]*@|postgresql://aise:${POSTGRES_PASS}@|g" docker-compose.yml

    # Redis password — update the redis command and all REDIS_URL references
    sed -i "s|redis-server --appendonly yes|redis-server --appendonly yes --requirepass ${REDIS_PASS}|g" docker-compose.yml
    sed -i "s|redis://redis:[0-9]*/0|redis://:${REDIS_PASS}@redis:6379/0|g" docker-compose.yml
    # Handle case where redis URL has no password yet
    sed -i "s|redis://redis:6379/0|redis://:${REDIS_PASS}@redis:6379/0|g" docker-compose.yml

    success "docker-compose.yml updated with matching credentials."
}

# ── Python dependencies ───────────────────────────────────────────────────────
install_python_deps() {
    info "Installing Python dependencies via Poetry..."
    export PATH="${HOME}/.local/bin:${PATH}"
    poetry install --no-interaction
    success "Python dependencies installed."
}

# ── Expose aise on system PATH ────────────────────────────────────────────────
install_aise_command() {
    info "Installing 'aise' command to /usr/local/bin..."
    export PATH="${HOME}/.local/bin:${PATH}"

    # Get the path to the aise binary inside the Poetry venv
    AISE_BIN="$(poetry env info --path)/bin/aise"

    if [ ! -f "$AISE_BIN" ]; then
        error "Could not find aise binary at ${AISE_BIN}. Did 'poetry install' succeed?"
    fi

    # Create a wrapper script so the venv Python is always used
    # Also cd to the project directory so .env is always found
    PROJ_DIR="$(pwd)"
    $SUDO tee /usr/local/bin/aise > /dev/null <<EOF
#!/usr/bin/env bash
# AiSE wrapper — runs inside its Poetry virtualenv from the project directory
# Change to project dir so .env is always found, unless user is already there
if [ ! -f ".env" ]; then
    cd "${PROJ_DIR}" 2>/dev/null || true
fi
exec "${AISE_BIN}" "\$@"
EOF
    $SUDO chmod +x /usr/local/bin/aise

    success "'aise' command installed at /usr/local/bin/aise"
    info "Test it with: aise --help"
}

# ── Playwright browsers ───────────────────────────────────────────────────────
install_playwright() {
    info "Installing Playwright chromium browser..."
    export PATH="${HOME}/.local/bin:${PATH}"
    poetry run playwright install chromium
    success "Playwright chromium installed."
}

# ── Interactive LLM setup ─────────────────────────────────────────────────────
configure_llm() {
    echo ""
    echo -e "${CYAN}┌─────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│         LLM Provider Setup              │${NC}"
    echo -e "${CYAN}└─────────────────────────────────────────┘${NC}"
    echo ""
    echo -e "  Select your LLM provider:"
    echo -e "  ${CYAN}1)${NC} Anthropic Claude  (cloud, requires API key)"
    echo -e "  ${CYAN}2)${NC} OpenAI GPT-4      (cloud, requires API key)"
    echo -e "  ${CYAN}3)${NC} DeepSeek          (cloud, requires API key)"
    echo -e "  ${CYAN}4)${NC} Ollama            (local, no API key needed)"
    echo ""

    local choice
    while true; do
        read -rp "  Enter choice [1-4]: " choice
        case "$choice" in
            1|2|3|4) break ;;
            *) echo -e "  ${RED}Invalid choice.${NC} Please enter 1, 2, 3, or 4." ;;
        esac
    done

    case "$choice" in
        1)
            set_env_var "LLM_PROVIDER" "anthropic"
            echo ""
            echo -e "  Get your API key from: ${CYAN}https://console.anthropic.com/${NC}"
            local api_key
            while true; do
                read -rsp "  Enter Anthropic API key: " api_key; echo ""
                [ -n "$api_key" ] && break
                warn "API key cannot be empty."
            done
            set_env_var "ANTHROPIC_API_KEY" "$api_key"
            success "Anthropic Claude configured."
            ;;
        2)
            set_env_var "LLM_PROVIDER" "openai"
            echo ""
            echo -e "  Get your API key from: ${CYAN}https://platform.openai.com/api-keys${NC}"
            local api_key
            while true; do
                read -rsp "  Enter OpenAI API key: " api_key; echo ""
                [ -n "$api_key" ] && break
                warn "API key cannot be empty."
            done
            set_env_var "OPENAI_API_KEY" "$api_key"
            success "OpenAI GPT-4 configured."
            ;;
        3)
            set_env_var "LLM_PROVIDER" "deepseek"
            echo ""
            echo -e "  Get your API key from: ${CYAN}https://platform.deepseek.com/${NC}"
            local api_key
            while true; do
                read -rsp "  Enter DeepSeek API key: " api_key; echo ""
                [ -n "$api_key" ] && break
                warn "API key cannot be empty."
            done
            set_env_var "DEEPSEEK_API_KEY" "$api_key"
            success "DeepSeek configured."
            ;;
        4)
            set_env_var "LLM_PROVIDER" "ollama"
            install_ollama
            configure_ollama_model
            ;;
    esac
}

install_ollama() {
    if command -v ollama &>/dev/null; then
        success "Ollama already installed: $(ollama --version 2>/dev/null || echo 'installed')"
        return
    fi

    info "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    # Start ollama service
    if systemctl is-active --quiet ollama 2>/dev/null; then
        success "Ollama service already running."
    else
        $SUDO systemctl enable --now ollama 2>/dev/null || ollama serve &>/dev/null &
        sleep 3
    fi
    success "Ollama installed."
}

configure_ollama_model() {
    echo ""
    echo -e "  Select an Ollama model to pull and use:"
    echo -e "  ${CYAN}1)${NC} phi3          (~2.3 GB) — Microsoft Phi-3 Mini, fast & efficient  [recommended]"
    echo -e "  ${CYAN}2)${NC} llama3        (~4.7 GB) — Meta Llama 3 8B, good general purpose"
    echo -e "  ${CYAN}3)${NC} mistral       (~4.1 GB) — Mistral 7B, fast and capable"
    echo -e "  ${CYAN}4)${NC} codellama     (~3.8 GB) — Code-focused, good for infra tasks"
    echo -e "  ${CYAN}5)${NC} llama3:70b    (~40 GB)  — Llama 3 70B, best quality (needs 64GB+ RAM)"
    echo -e "  ${CYAN}6)${NC} Custom        — Enter your own model name"
    echo ""

    local model_choice
    while true; do
        read -rp "  Enter choice [1-6, default=1]: " model_choice
        model_choice="${model_choice:-1}"
        case "$model_choice" in
            1|2|3|4|5|6) break ;;
            *) echo -e "  ${RED}Invalid choice.${NC}" ;;
        esac
    done

    local model_name
    case "$model_choice" in
        1) model_name="phi3" ;;
        2) model_name="llama3" ;;
        3) model_name="mistral" ;;
        4) model_name="codellama" ;;
        5) model_name="llama3:70b" ;;
        6)
            while true; do
                read -rp "  Enter model name (e.g. gemma2, qwen2): " model_name
                [ -n "$model_name" ] && break
                warn "Model name cannot be empty."
            done
            ;;
    esac

    # Ask for Ollama base URL (default localhost)
    local ollama_url
    read -rp "  Ollama base URL [http://localhost:11434]: " ollama_url
    ollama_url="${ollama_url:-http://localhost:11434}"

    set_env_var "OLLAMA_BASE_URL" "$ollama_url"
    set_env_var "OLLAMA_MODEL"    "$model_name"

    info "Pulling Ollama model '${model_name}' (this may take a while)..."
    ollama pull "$model_name" || warn "Could not pull model now. Run 'ollama pull ${model_name}' manually."
    success "Ollama configured with model: ${model_name}"
}

# ── Detect docker compose command (v2 plugin or v1 standalone) ───────────────
detect_docker_compose() {
    if docker compose version &>/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
        info "Using compose command: docker compose (v2)"
        return
    fi

    # v1 standalone is present but broken with newer Docker image formats.
    # Install the v2 plugin instead.
    info "docker compose v2 plugin not found — installing..."
    if [ "$PKG_FAMILY" = "debian" ]; then
        $SUDO $PKG_INSTALL docker-compose-plugin 2>/dev/null || true
    else
        $SUDO $PKG_INSTALL docker-compose-plugin 2>/dev/null || true
    fi

    if docker compose version &>/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
        info "Using compose command: docker compose (v2)"
        return
    fi

    # Last resort: fall back to v1 but warn loudly
    if command -v docker-compose &>/dev/null; then
        DOCKER_COMPOSE="docker-compose"
        warn "Using docker-compose v1 — if you hit 'ContainerConfig' errors, run:"
        warn "  sudo apt-get install docker-compose-plugin"
    else
        error "No Docker Compose found. Install with: sudo apt-get install docker-compose-plugin"
    fi
}

# ── Start infrastructure services ────────────────────────────────────────────
start_services() {
    info "Starting infrastructure services (postgres, redis, chromadb)..."

    # Create shared network if it doesn't exist
    docker network create aise-network 2>/dev/null || true

    # Create named volumes if they don't exist
    docker volume create aise_postgres_data 2>/dev/null || true
    docker volume create aise_redis_data    2>/dev/null || true
    docker volume create aise_chroma_data   2>/dev/null || true

    # ── PostgreSQL ──────────────────────────────────────────────────────────
    if docker ps -a --format '{{.Names}}' | grep -q "^aise-postgres$"; then
        if ! docker ps --format '{{.Names}}' | grep -q "^aise-postgres$"; then
            info "Starting existing aise-postgres container..."
            docker start aise-postgres
        else
            info "aise-postgres already running."
        fi
    else
        info "Creating aise-postgres..."
        docker run -d \
            --name aise-postgres \
            --network aise-network \
            --restart unless-stopped \
            -e POSTGRES_USER=aise \
            -e "POSTGRES_PASSWORD=${POSTGRES_PASS}" \
            -e POSTGRES_DB=aise \
            -p 5434:5432 \
            -v aise_postgres_data:/var/lib/postgresql/data \
            -v "$(pwd)/scripts/init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro" \
            postgres:16-alpine
    fi

    # ── Redis ───────────────────────────────────────────────────────────────
    if docker ps -a --format '{{.Names}}' | grep -q "^aise-redis$"; then
        if ! docker ps --format '{{.Names}}' | grep -q "^aise-redis$"; then
            info "Starting existing aise-redis container..."
            docker start aise-redis
        else
            info "aise-redis already running."
        fi
    else
        info "Creating aise-redis..."
        docker run -d \
            --name aise-redis \
            --network aise-network \
            --restart unless-stopped \
            -p 6380:6379 \
            -v aise_redis_data:/data \
            redis:7-alpine \
            redis-server --appendonly yes \
                --requirepass "${REDIS_PASS}" \
                --maxmemory 256mb \
                --maxmemory-policy allkeys-lru
    fi

    # ── ChromaDB ────────────────────────────────────────────────────────────
    if docker ps -a --format '{{.Names}}' | grep -q "^aise-chromadb$"; then
        if ! docker ps --format '{{.Names}}' | grep -q "^aise-chromadb$"; then
            info "Starting existing aise-chromadb container..."
            docker start aise-chromadb
        else
            info "aise-chromadb already running."
        fi
    else
        info "Creating aise-chromadb..."
        docker run -d \
            --name aise-chromadb \
            --network aise-network \
            --restart unless-stopped \
            -p 8000:8000 \
            -v aise_chroma_data:/chroma/chroma \
            -e IS_PERSISTENT=TRUE \
            -e ANONYMIZED_TELEMETRY=FALSE \
            chromadb/chroma:latest
    fi

    info "Waiting for services to become ready..."
    sleep 8
    success "Infrastructure services started."
}

# ── Verify services ───────────────────────────────────────────────────────────
verify_services() {
    info "Verifying service connectivity..."

    # PostgreSQL
    if docker exec aise-postgres pg_isready -U aise -d aise &>/dev/null; then
        success "PostgreSQL: reachable"
    else
        warn "PostgreSQL: not yet ready (may still be initializing)"
    fi

    # Redis
    if docker exec aise-redis redis-cli -a "${REDIS_PASS}" ping 2>/dev/null | grep -q PONG; then
        success "Redis: reachable"
    else
        warn "Redis: not yet ready"
    fi

    # ChromaDB
    if curl -sf http://localhost:8000/api/v2/heartbeat &>/dev/null || \
       curl -sf http://localhost:8000/api/v1/heartbeat &>/dev/null; then
        success "ChromaDB: reachable"
    else
        warn "ChromaDB: not yet ready"
    fi
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   AiSE - AI Support Engineer Installer   ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
    echo ""

    detect_os
    check_root
    install_system_deps
    install_docker
    detect_docker_compose
    install_poetry
    setup_env
    configure_llm
    sync_docker_compose
    install_python_deps
    install_aise_command
    install_playwright
    start_services
    verify_services

    # Determine which model is configured for the summary
    CONFIGURED_PROVIDER=$(grep -oP '(?<=LLM_PROVIDER=)\S+' .env | head -1 || echo "unknown")
    CONFIGURED_MODEL=$(grep -oP '(?<=OLLAMA_MODEL=)\S+' .env | head -1 || echo "")

    echo ""
    success "Installation complete."
    echo ""
    echo -e "  ${CYAN}aise${NC} is now available as a system command."
    echo ""
    echo -e "  Provider : ${YELLOW}${CONFIGURED_PROVIDER}${NC}"
    [ -n "$CONFIGURED_MODEL" ] && echo -e "  Model    : ${YELLOW}${CONFIGURED_MODEL}${NC}"
    echo ""
    echo -e "  Quick start:"
    echo -e "    ${CYAN}aise ask \"Why is my EC2 instance unreachable?\"${NC}"
    echo -e "    ${CYAN}aise learn list${NC}"
    echo -e "    ${CYAN}aise learn enable kubernetes${NC}"
    echo -e "    ${CYAN}aise --help${NC}"
    echo ""
    [ "$CONFIGURED_PROVIDER" = "ollama" ] && \
        echo -e "  Ollama tip: if the service isn't running, start it with ${CYAN}ollama serve${NC}"
    echo ""
}

main "$@"
