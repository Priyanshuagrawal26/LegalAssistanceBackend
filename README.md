# AI-Driven Legal Assistance

A FastAPI-based application that provides AI-powered legal document analysis using Azure services. The system can classify documents, extract clauses, and provide detailed analysis of legal contracts.

## Features

- **Document Upload**: Support for PDF, DOCX, DOC, and various image formats
- **OCR Processing**: Extract text from documents using Azure Form Recognizer
- **Document Classification**: Classify documents into categories (NDA, MSA, SOW, etc.)
- **Clause Extraction**: Automatically segment and classify contract clauses
- **Azure Integration**: Leverages Azure Blob Storage, Form Recognizer, and OpenAI services

## Architecture

```
User Upload → Azure Blob Storage → Azure OCR → Document Classification → Clause Extraction
```

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd "AI Driven Legal Assistance"
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   
   Create a `.env` file in the root directory with the following variables:
   ```env
   # Azure Blob Storage
   AZURE_STORAGE_CONNECTION_STRING=your_connection_string
   AZURE_BLOB_CONTAINER_NAME=your_container_name
   
   # Azure Form Recognizer
   AZURE_FORM_RECOGNIZER_ENDPOINT=your_endpoint
   AZURE_FORM_RECOGNIZER_KEY=your_key
   
   # Azure OpenAI
   AZURE_OPENAI_API_KEY=your_api_key
   AZURE_OPENAI_API_VERSION=2025-01-01-preview
   AZURE_OPENAI_ENDPOINT=your_endpoint
   AZURE_OPENAI_DEPLOYMENT_NAME=your_model_name
   
   # Azure AI Projects (for document classification)
   # These are configured in the main.py file
   ```

## Usage

1. **Start the application**
   ```bash
   python legal_assistant.py
   ```
   
   Or using uvicorn directly:
   ```bash
   uvicorn legal_assistant:app --reload
   ```

2. **Access the API**
   - API documentation: `http://localhost:8000/docs`
   - Interactive API: `http://localhost:8000/redoc`

3. **Upload documents**
   ```bash
   curl -X POST "http://localhost:8000/upload/" \
        -H "accept: application/json" \
        -H "Content-Type: multipart/form-data" \
        -F "file=@your_document.pdf"
   ```

## API Endpoints

### GET `/`
Health check endpoint.

### GET `/health`
Detailed service health check.

### POST `/upload/`
Upload and process a legal document.

**Request:**
- `file`: Multipart file upload (PDF, DOCX, DOC, JPG, PNG, etc.)

**Response:**
```json
{
  "filename": "contract.pdf",
  "blob_url": "https://storage.blob.core.windows.net/...",
  "classification": "NDA",
  "clauses": [
    {
      "content": "Clause text...",
      "clause_type": "Confidentiality",
      "explanation": "This clause establishes..."
    }
  ],
  "status": "success"
}
```

### POST `/classify-text/`
Classify text content directly without file upload.

**Request:**
```json
{
  "text": "Your contract text here..."
}
```

### POST `/extract-clauses/`
Extract and classify clauses from text content.

**Request:**
```json
{
  "text": "Your contract text here..."
}
```

## Project Structure

```
AI Driven Legal Assistance/
├── legal_assistant.py      # 🎯 MAIN APPLICATION - All core functionality
├── embedding_generator.py  # Advanced embeddings (optional)
├── clause_comparison.py    # Clause comparison utilities (optional)
├── approved_clause_api.py  # Template management (optional)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not in git)
├── .gitignore             # Git ignore rules
├── README.md              # This file
├── uploads/               # Local file storage (temporary)
└── .venv/                 # Virtual environment
```

### 🚀 **Simplified Architecture**
The entire application is now consolidated into **`legal_assistant.py`** which contains:
- FastAPI web server
- Azure Blob Storage integration
- Azure Form Recognizer (OCR)
- Azure OpenAI for document & clause classification
- Complete document processing pipeline
- All API endpoints

## Dependencies

- **FastAPI**: Web framework for building APIs
- **uvicorn**: ASGI server for FastAPI
- **azure-storage-blob**: Azure Blob Storage client
- **azure-ai-formrecognizer**: Azure Form Recognizer for OCR
- **azure-ai-projects**: Azure AI Projects for agent-based classification
- **openai**: Azure OpenAI client for clause classification
- **python-dotenv**: Environment variable management
- **python-multipart**: File upload support

## Development

### Code Style
This project follows PEP 8 Python style guidelines with:
- 4-space indentation
- Maximum line length of 88 characters
- Comprehensive docstrings for all functions
- Type hints for function parameters and returns

### Testing
Run tests with:
```bash
pytest
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make changes following the established code style
4. Add tests for new functionality
5. Submit a pull request

## Security Notes

- Never commit API keys or sensitive configuration to version control
- Use environment variables for all sensitive data
- The `.env` file is included in `.gitignore` for security
- Uploaded files are temporarily stored locally and in Azure Blob Storage

## License

[Add your license information here]

## Support

For issues and questions, please [create an issue](link-to-issues) in the repository.
