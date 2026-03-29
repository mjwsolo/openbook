#!/bin/bash
# openbook installer — one command install
set -e

REPO="mjwsolo/openbook"
INSTALL_DIR="$HOME/.openbook"
BIN_NAME="openbook"

echo ""
echo "  ⣿ installing openbook..."
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 is required but not found."
    echo "    Install it from https://python.org"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PY_VERSION found"

# Create install directory
mkdir -p "$INSTALL_DIR"

# Download latest openbook.py
echo "  ↓ Downloading openbook..."
curl -fsSL "https://raw.githubusercontent.com/$REPO/main/openbook.py" -o "$INSTALL_DIR/openbook.py"
chmod +x "$INSTALL_DIR/openbook.py"
echo "  ✓ Downloaded to $INSTALL_DIR/openbook.py"

# Create launcher script
cat > "$INSTALL_DIR/openbook" << 'EOF'
#!/bin/bash
python3 "$HOME/.openbook/openbook.py" "$@"
EOF
chmod +x "$INSTALL_DIR/openbook"

# Add to PATH
SHELL_NAME=$(basename "$SHELL")
PROFILE=""
if [ "$SHELL_NAME" = "zsh" ]; then
    PROFILE="$HOME/.zshrc"
elif [ "$SHELL_NAME" = "bash" ]; then
    PROFILE="$HOME/.bashrc"
    [ -f "$HOME/.bash_profile" ] && PROFILE="$HOME/.bash_profile"
elif [ "$SHELL_NAME" = "fish" ]; then
    PROFILE="$HOME/.config/fish/config.fish"
fi

PATH_LINE='export PATH="$HOME/.openbook:$PATH"'
if [ "$SHELL_NAME" = "fish" ]; then
    PATH_LINE='set -gx PATH $HOME/.openbook $PATH'
fi

if [ -n "$PROFILE" ]; then
    if ! grep -q ".openbook" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "# openbook" >> "$PROFILE"
        echo "$PATH_LINE" >> "$PROFILE"
        echo "  ✓ Added to PATH in $PROFILE"
    else
        echo "  ✓ Already in PATH"
    fi
fi

# Add to current session
export PATH="$HOME/.openbook:$PATH"

echo ""
echo "  ✓ openbook installed!"
echo ""
echo "  Run it now:"
echo "    openbook"
echo ""
echo "  Or if 'openbook' isn't found yet, restart your terminal or run:"
echo "    source $PROFILE"
echo ""

# Run it immediately
exec python3 "$INSTALL_DIR/openbook.py" "$@"
