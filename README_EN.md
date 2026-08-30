# arXiv Paper Summary Tool

A locally deployable web tool that accepts arXiv paper links, automatically downloads PDFs, and uses LLMs to generate structured summaries with history tracking.

## ✨ Features

- 🔗 **arXiv Link Support**: Automatically recognizes and parses arXiv paper links
- 📄 **Auto Download**: Downloads PDF papers locally with smart naming (format: `Year_Title.pdf`)
- 🤖 **AI Smart Summary**: Calls LLM to generate structured Chinese summaries (TL;DR, Motivation, Methods, Results, Conclusion)
- 📖 **Full-text Deep Analysis**: Generates detailed Chinese analysis reports based on complete paper content
- 🔄 **Optional AI Summary**: Enables/disables AI summary feature for flexible usage
- 🔄 **Re-analysis**: Supports re-generating AI summaries and full-text analysis for updates or corrections
- 💾 **Markdown Export**: Exports full analysis results as Markdown files
- 📚 **History Records**: Saves processing history with pagination support for easy viewing and management
- ⏰ **Version Tracking**: Displays paper submission and revision timestamps
- 📱 **Responsive Design**: Works on desktop and mobile devices
- 🎨 **Modern UI**: Clean and beautiful interface with LaTeX formula rendering
- ⚡ **Async Processing**: AI summaries and analysis generated asynchronously without blocking the UI
- 🔒 **Security Enhanced**: Supports SECRET_KEY environment variable, API key format validation, thread-safe proxy handling

Demo URL: http://arxiv-parser.iepose.cn/
<img src="assets/demo.png" width="80%" alt="Demo Screenshot">

> ⚠️ **Note**: The demo site (http://arxiv-parser.iepose.cn/) currently has expired API keys, so AI summary and analysis features are temporarily unavailable. It's recommended to clone this project locally, configure your own API key, and deploy it for full experience.

## 🛠️ Tech Stack

- **Backend**: Python + Flask
- **Frontend**: HTML5 + CSS3 + JavaScript
- **Database**: SQLite (local storage)
- **Paper Download**: arXiv Python library
- **HTTP Client**: httpx (thread-safe proxy handling)

## 📦 Installation & Deployment

### Prerequisites

- Python 3.7+
- pip package manager
- LLM API Key

### Installation Steps

#### Recommended: Using Conda

1. **Clone the repository**
   ```bash
   git clone https://github.com/wqs111000/arxiv_parser.git
   cd arxiv_parser
   ```

2. **Create and activate Conda environment**
   ```bash
   # Automatically create environment and install dependencies
   conda env create -f environment.yml

   # Activate environment
   conda activate arxiv_parser
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env file, fill in your API Key and configure security key
   # Example: OPENAI_API_KEY=sk-... and SECRET_KEY=<random-key>
   ```

4. **Start the application**
   ```bash
   python app.py
   ```

### Alternative: Using Docker

1. **Prepare environment variables**

   Create (or copy) `.env` file in the project root directory, ensuring at least:

   ```bash
   OPENAI_API_KEY=your_API_Key
   SECRET_KEY=randomly_generated_key (required for production)
   # For DeepSeek:
   # OPENAI_BASE_URL=https://api.deepseek.com/v1
   # DEFAULT_MODEL=deepseek-chat
   # For OpenAI:
   # DEFAULT_MODEL=gpt-3.5-turbo
   ```

2. **Build and run directly with Docker**

   ```bash
   docker build -t arxiv_parser .
   docker run -d \
     --name arxiv_parser \
     -p 5000:5000 \
     -e OPENAI_API_KEY=${OPENAI_API_KEY} \
     -e SECRET_KEY=${SECRET_KEY} \
     -e OPENAI_BASE_URL=${OPENAI_BASE_URL} \
     -e DEFAULT_MODEL=${DEFAULT_MODEL} \
     -e FLASK_PORT=5000 \
     -e TZ=Asia/Shanghai \
     -v $(pwd)/data:/app/data \
     arxiv_parser
   ```

3. **Using docker-compose**

   `docker-compose.yml` is provided. Execute in the project root directory:

   ```bash
   # Ensure current directory has .env containing OPENAI_API_KEY and other variables
   docker compose up -d
   docker compose down            # Stop and remove containers
   docker compose restart
   docker compose up -d --build   # Restart in background and rebuild images and containers
   docker compose build           # Build image only, don't start
   ```

### Access the Application

After starting, open browser to access: http://localhost:5000

## 📝 Usage

### Basic Workflow

1. **Configure Model** (first-time use)
   - Copy `.env.example` to `.env`
   - Edit `.env` file, fill in API key and set model
   - Example: `OPENAI_API_KEY=sk-...` and `DEFAULT_MODEL=gpt-3.5-turbo`
   - Set `SECRET_KEY` to a strong random value for production

2. **Enter Paper Link**: Paste arXiv paper link in the input box
   - Supported formats: `https://arxiv.org/abs/xxxx.xxxxx`
   - Supported formats: `https://arxiv.org/pdf/xxxx.xxxxx`

3. **Choose AI Summary Option**: Check or uncheck "Enable Summary"
   - **Enabled**: Download paper + Generate AI summary (async processing)
   - **Disabled**: Only download paper, click "Complete AI Summary Later" if needed

4. **Start Processing**: Click "Start Processing" button
   - Automatically downloads PDF to `data/pdfs/` directory
   - Smart naming format: `Year_Title.pdf`

5. **View Results**: Page displays paper information and AI summary
   - Shows paper title, authors, abstract
   - Displays version records (submission and revision times)
   - Shows AI model used
   - Displays AI-generated structured summary
   - PDF file downloadable

6. **Full-text Deep Analysis**
   - Click "Start Full Analysis" to generate deep analysis report based on complete paper content
   - After analysis completion, click "Download Markdown" to export results

7. **Re-analysis**
   - Click "Re-summarize" to reset and regenerate AI summary
   - Click "Re-analyze" to reset and redo full-text analysis

8. **History Records**: View "History" panel on the right
   - Automatically loads and displays all processed papers (with pagination)
   - Click any history record to load paper details
   - Automatically fills corresponding arXiv URL when loading
   - Status icons show whether AI summary and full analysis are completed

### Example Links

- Attention Is All You Need: https://arxiv.org/abs/1706.03762
- BERT: https://arxiv.org/abs/1810.04805
- Vision Transformer: https://arxiv.org/abs/2010.11929

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required | `sk-...` |
| `SECRET_KEY` | Flask session encryption key | Auto-generated | `<random-hex>` |
| `DEFAULT_MODEL` | AI model to use | `deepseek-chat` | `gpt-3.5-turbo`, `gpt-4`, `deepseek-chat` |
| `OPENAI_BASE_URL` | API base URL | `https://api.openai.com/v1` | `https://api.deepseek.com/v1` |
| `FLASK_PORT` | Application port | `5000` | `5001` |

### Model Configuration

Configure AI models in `.env` file:

```bash
# Use OpenAI GPT-3.5
OPENAI_API_KEY=your-openai-key
SECRET_KEY=$(python -c "import os; print(os.urandom(24).hex())")
DEFAULT_MODEL=gpt-3.5-turbo

# Use OpenAI GPT-4
OPENAI_API_KEY=your-openai-key
SECRET_KEY=$(python -c "import os; print(os.urandom(24).hex())")
DEFAULT_MODEL=gpt-4

# Use DeepSeek
OPENAI_API_KEY=your-deepseek-key
SECRET_KEY=$(python -c "import os; print(os.urandom(24).hex())")
OPENAI_BASE_URL=https://api.deepseek.com/v1
DEFAULT_MODEL=deepseek-chat
```

**Supported Models**:
- `gpt-3.5-turbo` - OpenAI GPT-3.5 (cost-effective)
- `gpt-4` - OpenAI GPT-4 (smarter but more expensive)
- `deepseek-chat` - DeepSeek (available in China, cost-effective)
- Other models compatible with OpenAI API format

## 📁 Project Structure

```
arxiv_parser/
├── app.py                  # Main Flask application file
├── prompts.py              # Unified AI prompt management
├── requirements.txt        # Python dependencies
├── environment.yml         # Conda environment configuration
├── docker-compose.yml      # Docker Compose configuration
├── Dockerfile              # Docker image configuration
├── README.md               # Project documentation
├── .env.example            # Environment variable example
├── .gitignore              # Git ignore file
├── templates/
│   └── index.html          # Frontend page
├── static/
│   ├── css/
│   │   └── style.css       # Stylesheet
│   └── js/
│       └── app.js          # Frontend logic
├── data/
│   ├── pdfs/               # Downloaded PDF files (auto-created)
│   └── arxiv_history.db    # SQLite database (auto-generated)
└── assets/                 # Project resource files
```

## 🔍 Feature Details

### Paper Download & Naming
- Uses official arXiv Python library to download PDFs
- Automatically saves to `data/pdfs/` directory
- Smart filename format: `{Year}_{Title}.pdf`
- Example: `2017_Attention Is All You Need.pdf`
- Automatically cleans illegal characters in titles (such as `:`, `/`, `\`, `|`, `?`, `*`, `<`, `>`)
- Avoids filename conflicts and filesystem limitations
- PDF integrity verification, automatically detects and redownloads corrupted files

### AI Summary Generation
- Generates structured Chinese summaries based on paper abstracts
- Contains 5 sections: TL;DR (one-sentence summary), Motivation, Methods, Results, Conclusion
- Async processing without blocking UI, real-time status viewing
- Supports multiple LLMs (OpenAI GPT-3.5/GPT-4, DeepSeek, etc.)
- Word count controlled between 300-500 words, professional and concise
- Thread-safe API calls, supports concurrent requests

### Full-text Deep Analysis
- Performs deep analysis based on complete PDF content
- Uses `qwen-long` model for long text processing
- Generates detailed Chinese analysis reports saved as Markdown
- Supports export download, filenames correspond to PDFs
- Async processing with real-time status viewing

### Re-analysis Feature
- Supports resetting AI summary status and regenerating
- Supports resetting full analysis status and reanalyzing
- Automatically starts new analysis process after reset
- Simultaneously deletes locally saved analysis files

### Version Record Display
- Automatically extracts version information from arXiv data
- Displays paper submission time and last revision time
- Format example: `Published 12 Jun 2017, revised 2 Aug 2023`
- Helps understand paper update history and timeliness

### Optional AI Summary Feature
- Provides "Enable Summary" checkbox
- **When enabled**: Download paper + Immediately generate AI summary (async)
- **When disabled**: Only download paper, shows "Not Enabled" status
- Supports clicking "Complete AI Summary Later" button to supplement generation
- Flexible to meet different usage scenarios

### History Record Management
- Uses SQLite local database storage, no extra configuration needed
- Saves paper metadata, summary results, and processing status
- Right sidebar displays history list in real-time (with pagination)
- Each record shows: title, version record (truncated), completion time (Beijing time), status icon
- Click any record to automatically load paper details
- Automatically fills corresponding arXiv URL in input box when loading
- Supports status filtering: Completed (green checkmark), Processing (yellow hourglass)

### Time Display
- All times automatically converted to Beijing time (UTC+8)
- Uniform format: `YYYY.MM.DD-HH:MM:SS`
- Example: `2026.03.11-16:45:30`
- Easy for domestic users to read and understand

### Interface Features
- Responsive design, perfectly adapts to desktop and mobile devices
- Bootstrap 5 framework, modern UI components
- KaTeX supports LaTeX formula rendering
- Real-time status updates and auto-refresh
- Friendly error messages and Toast notifications
- Loading animations and transition effects enhance user experience
- Simple and intuitive operation flow reduces usage threshold

### Security Features
- SECRET_KEY read from environment variables, must be configured for production
- API Key format validation prevents invalid requests
- File upload size limit (50MB)
- Thread-safe HTTP client avoids race conditions
- Filename URL encoding supports Chinese and special characters

## 💡 Usage Recommendations

1. **API Costs**: Be aware of API call costs; full-text analysis using long-text models may consume many tokens
2. **Network Connection**: Ensure access to arXiv and LLM APIs
3. **Storage Space**: PDF files and analysis results will occupy local storage space
4. **Privacy Protection**: Paper data and API keys stored locally, not uploaded to servers
5. **Production Deployment**: Must set strong random `SECRET_KEY`, do not use default values


## 🚀 Advanced Features

### Batch Processing
Can implement batch paper processing by modifying API interfaces

### Custom Prompts
Modify prompts in `prompts.py` file to customize summary and analysis styles

### Other AI Providers
Supports any service compatible with OpenAI API format

## 📄 License

MIT License

## 🤝 Contributing

Issues and Pull Requests are welcome!

## 📧 Contact

For questions or suggestions, please create a GitHub Issue.

---

**Note**:
This project is for learning and research purposes only. Please comply with arXiv and AI service provider terms of use.
Mainly developed using WorkBuddy with kimi-k2-thinking model via vibe coding.
Project reference: https://github.com/dw-dengwei/daily-arXiv-ai-enhanced
