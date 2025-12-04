#!/bin/bash
#
# Claude Adopter Finder - One-Click Setup for Mac
#
# Usage: Open Terminal, navigate to this folder, run: ./setup.sh
#

set -e

echo ""
echo "=========================================="
echo "  Claude Adopter Finder - Setup"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Installing to: $SCRIPT_DIR"
echo ""

# Step 1: Check/Install uv
echo "Step 1/4: Checking for uv..."
if command -v uv &> /dev/null; then
    UV_PATH=$(which uv)
    echo -e "${GREEN}✓ uv already installed at: $UV_PATH${NC}"
else
    echo "Installing uv (Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    if command -v uv &> /dev/null; then
        UV_PATH=$(which uv)
        echo -e "${GREEN}✓ uv installed at: $UV_PATH${NC}"
    else
        UV_PATH="$HOME/.local/bin/uv"
        echo -e "${YELLOW}uv installed at: $UV_PATH${NC}"
    fi
fi
echo ""

# Step 2: Install Python dependencies
echo "Step 2/4: Installing Python dependencies..."
"$HOME/.local/bin/uv" sync 2>/dev/null || uv sync
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Step 3: Setup GitHub token
echo "Step 3/4: Setting up GitHub token..."
if [ -f ".env" ]; then
    echo -e "${YELLOW}→ .env file already exists${NC}"
    read -p "Do you want to update the GitHub token? (y/N): " update_token
    if [[ $update_token =~ ^[Yy]$ ]]; then
        setup_token=true
    else
        setup_token=false
    fi
else
    setup_token=true
fi

if [ "$setup_token" = true ]; then
    echo ""
    echo "You need a GitHub token (free) to search for Claude usage."
    echo ""
    echo "To create one:"
    echo "  1. Go to: https://github.com/settings/tokens"
    echo "  2. Click 'Generate new token (classic)'"
    echo "  3. Name it 'claude-adopter-finder'"
    echo "  4. Select scopes: 'public_repo' and 'read:org'"
    echo "  5. Click 'Generate token' and copy it"
    echo ""
    read -p "Paste your GitHub token here (or press Enter to skip): " github_token

    if [ -n "$github_token" ]; then
        echo "GITHUB_TOKEN=$github_token" > .env
        echo "# Optional: Add TheirStack API key for job posting search" >> .env
        echo "# THEIRSTACK_API_KEY=" >> .env
        echo -e "${GREEN}✓ GitHub token saved to .env${NC}"
    else
        echo "GITHUB_TOKEN=" > .env
        echo -e "${YELLOW}→ Skipped. Add your token to .env later${NC}"
    fi
fi
echo ""

# Step 4: Generate Claude Desktop config
echo "Step 4/4: Generating Claude Desktop configuration..."
UV_FULL_PATH="$HOME/.local/bin/uv"

# Create the config snippet
CONFIG_FILE="$SCRIPT_DIR/config/my_claude_config_snippet.json"
cat > "$CONFIG_FILE" << EOF
{
  "mcpServers": {
    "claude-adopter-finder": {
      "command": "$UV_FULL_PATH",
      "args": [
        "run",
        "--directory",
        "$SCRIPT_DIR",
        "python",
        "-m",
        "src.combined_scanner"
      ]
    }
  }
}
EOF

echo -e "${GREEN}✓ Config generated${NC}"
echo ""

# Done!
echo "=========================================="
echo -e "${GREEN}  Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Open Claude Desktop settings and add this MCP server."
echo "   Config file location:"
echo "   ~/Library/Application Support/Claude/claude_desktop_config.json"
echo ""
echo "2. Add this to your mcpServers section:"
echo ""
echo -e "${YELLOW}   \"claude-adopter-finder\": {"
echo "     \"command\": \"$UV_FULL_PATH\","
echo "     \"args\": ["
echo "       \"run\","
echo "       \"--directory\","
echo "       \"$SCRIPT_DIR\","
echo "       \"python\","
echo "       \"-m\","
echo "       \"src.combined_scanner\""
echo "     ]"
echo -e "   }${NC}"
echo ""
echo "3. Restart Claude Desktop"
echo ""
echo "4. Test by asking: \"Check API status for Claude Adopter Finder\""
echo ""
echo "Full config snippet saved to:"
echo "  $CONFIG_FILE"
echo ""
