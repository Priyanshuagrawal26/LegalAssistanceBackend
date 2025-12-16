# AI-Driven Legal Assistance API Documentation

## Overview
This API provides complete legal document analysis including clause extraction, classification, embedding generation, and compliance checking against approved templates.

## Base URL
```
http://localhost:8000
```

## Storage Locations

### Azure Blob Storage Structure:
- **Storage Account:** `aisa0101`
- **Container:** `testagent`
- **Document Embeddings:** `embeddings/` folder
- **Approved Templates:** `approved_templates/` folder  
- **Compliance Reports:** `compliance_reports/` folder

## API Endpoints

### 1. Document Processing

#### Upload and Process Document
```http
POST /upload/
Content-Type: multipart/form-data
```

**Upload a legal document for complete processing:**
- OCR text extraction
- Document classification
- Clause segmentation and classification
- Embedding generation
- Storage in Azure Blob Storage

**Example Response:**
```json
{
  "filename": "contract.pdf",
  "blob_url": "https://aisa0101.blob.core.windows.net/testagent/contract.pdf",
  "classification": "Service Agreement",
  "clauses": [
    {
      "content": "The Company shall indemnify...",
      "clause_type": "Indemnification",
      "explanation": "This clause protects..."
    }
  ],
  "embeddings": {
    "blob_url": "https://aisa0101.blob.core.windows.net/testagent/embeddings/contract_embeddings_20240821_123456.json",
    "document_id": "uuid-here",
    "total_clauses": 5
  }
}
```

### 2. Template Management

#### Upload Approved Templates
```http
POST /templates/upload
Content-Type: application/json
```

**Upload approved clause templates for compliance checking:**

**Request Body:**
```json
{
  "templates": [
    {
      "clause_type": "Indemnification",
      "content": "The Service Provider shall indemnify, defend, and hold harmless...",
      "description": "Standard indemnification clause",
      "risk_level": "Low",
      "compliance_notes": "Approved by Legal Team",
      "version": "2.1",
      "approved_by": "Legal Department"
    }
  ]
}
```

**Example Response:**
```json
{
  "status": "success",
  "template_library_url": "https://aisa0101.blob.core.windows.net/testagent/approved_templates/approved_clause_library.json",
  "templates_uploaded": 5,
  "summary": {
    "total_templates": 5,
    "clause_types": {
      "Indemnification": 1,
      "Termination": 1,
      "Payment Terms": 1
    }
  }
}
```

#### List Template Libraries
```http
GET /templates/list
```

**Get all approved template libraries:**

**Example Response:**
```json
{
  "total_libraries": 1,
  "template_libraries": [
    {
      "name": "approved_templates/approved_clause_library.json",
      "url": "https://aisa0101.blob.core.windows.net/testagent/approved_templates/approved_clause_library.json",
      "last_modified": "2024-08-21T10:30:00+00:00",
      "size": 15420
    }
  ]
}
```

#### Get Template Summary
```http
GET /templates/summary
```

**Get summary of current approved templates:**

**Example Response:**
```json
{
  "library_id": "uuid-here",
  "created_at": "2024-08-21T10:30:00",
  "total_templates": 5,
  "successful_templates": 5,
  "clause_types": {
    "Indemnification": 1,
    "Termination": 1,
    "Payment Terms": 1,
    "Confidentiality": 1,
    "Governing Law": 1
  },
  "risk_levels": {
    "Low": 4,
    "Medium": 1
  }
}
```

### 3. Clause Comparison

#### Compare Document Against Templates
```http
GET /compare/document/{document_blob_name}?min_similarity=0.7
```

**Compare document clauses against approved templates using cosine similarity:**

**Example:** 
```
GET /compare/document/embeddings/contract_embeddings_20240821_123456.json?min_similarity=0.8
```

**Example Response:**
```json
{
  "comparison_id": "uuid-here",
  "compared_at": "2024-08-21T10:35:00",
  "total_clauses": 5,
  "min_similarity_threshold": 0.8,
  "clause_comparisons": [
    {
      "clause_id": "uuid-here",
      "clause_type": "Indemnification",
      "content_preview": "The Company shall indemnify and hold harmless...",
      "similar_templates": [
        {
          "template_id": "uuid-here",
          "similarity_score": 0.92,
          "match_quality": "Excellent Match",
          "risk_level": "Low"
        }
      ],
      "best_match_similarity": 0.92,
      "compliance_status": {
        "status": "Fully Compliant",
        "risk_level": "Low",
        "reason": "Excellent match with approved template",
        "recommendations": ["No action required"]
      }
    }
  ],
  "summary": {
    "clauses_with_matches": 4,
    "clauses_without_matches": 1,
    "high_risk_clauses": 1,
    "compliance_issues": [
      {
        "clause_id": "uuid-here",
        "issue": "No matching approved template found",
        "clause_type": "Custom Clause"
      }
    ]
  },
  "compliance_report_url": "https://aisa0101.blob.core.windows.net/testagent/compliance_reports/contract_compliance_20240821_123456.json"
}
```

#### Compare Clauses (POST)
```http
POST /compare/clauses
Content-Type: application/json
```

**Request Body:**
```json
{
  "document_embedding_blob": "embeddings/contract_embeddings_20240821_123456.json",
  "min_similarity": 0.7
}
```

### 4. Embedding Management

#### List All Embeddings
```http
GET /embeddings/list
```

**Get all stored document embeddings:**

**Example Response:**
```json
{
  "total_files": 3,
  "embedding_files": [
    {
      "name": "embeddings/contract_embeddings_20240821_123456.json",
      "url": "https://aisa0101.blob.core.windows.net/testagent/embeddings/contract_embeddings_20240821_123456.json",
      "last_modified": "2024-08-21T10:30:00+00:00",
      "size": 45678
    }
  ]
}
```

#### Get Clauses from Embedding File
```http
GET /embeddings/{blob_name}/clauses
```

**Retrieve all clauses from a specific embedding file:**

**Example:**
```
GET /embeddings/embeddings/contract_embeddings_20240821_123456.json/clauses
```

### 5. Compliance Reports

#### List Compliance Reports
```http
GET /compliance/reports
```

**Get all generated compliance reports:**

**Example Response:**
```json
{
  "total_reports": 2,
  "compliance_reports": [
    {
      "name": "compliance_reports/contract_compliance_20240821_123456.json",
      "url": "https://aisa0101.blob.core.windows.net/testagent/compliance_reports/contract_compliance_20240821_123456.json",
      "last_modified": "2024-08-21T10:35:00+00:00",
      "size": 12345
    }
  ]
}
```

## How to Fetch Clauses

### Method 1: Via API
```bash
# List all embedding files
curl http://localhost:8000/embeddings/list

# Get clauses from specific file
curl http://localhost:8000/embeddings/embeddings/contract_embeddings_20240821_123456.json/clauses
```

### Method 2: Programmatically
```python
from embedding_generator import ClauseEmbeddingGenerator

generator = ClauseEmbeddingGenerator()

# List available files
files = generator.list_stored_embeddings()

# Download clauses from specific file
clauses = generator.download_and_get_clauses("embeddings/contract_embeddings_20240821_123456.json")

# Each clause contains:
# - clause_id
# - content
# - clause_type
# - explanation
# - embedding (vector)
# - similarity scores (when compared)
```

### Method 3: Direct Azure Blob Access
```python
from azure.storage.blob import BlobServiceClient
import json
import os

# Initialize blob client
blob_service_client = BlobServiceClient.from_connection_string(
    os.getenv("AZURE_STORAGE_CONNECTION_STRING")
)

# Download specific embedding file
blob_client = blob_service_client.get_blob_client("testagent", "embeddings/contract_embeddings_20240821_123456.json")
blob_data = blob_client.download_blob().readall()
data = json.loads(blob_data.decode('utf-8'))

# Access clauses
clauses = data.get('clauses', [])
```

## Workflow Examples

### Complete Document Processing
```python
# 1. Upload document via API
# 2. System automatically:
#    - Extracts text (OCR)
#    - Classifies document
#    - Segments clauses
#    - Classifies each clause
#    - Generates embeddings
#    - Stores in Azure Blob Storage

# 3. Compare against approved templates
# 4. Generate compliance report
```

### Template Management
```python
# 1. Upload approved templates via API
# 2. System generates embeddings for templates
# 3. Stores in approved_templates/ folder
# 4. Uses for future compliance checking
```

## Testing

### Run Complete Workflow Test
```bash
python test_complete_workflow.py
```

### Check Current Storage
```bash
python check_embeddings.py
```

### Start API Server
```bash
python enhanced_main.py
```

## Error Handling

Common issues and solutions:

1. **No embeddings found:** Run `python test_complete_workflow.py` to create sample data
2. **Deployment not found:** Check Azure OpenAI embedding deployment name in `.env`
3. **Blob access error:** Verify Azure Storage credentials and container existence
4. **Low similarity scores:** Adjust `min_similarity` parameter (try 0.5-0.9 range)

## Data Schema

### Clause with Embedding
```json
{
  "clause_id": "uuid",
  "content": "Full clause text",
  "clause_type": "Indemnification",
  "explanation": "Human-readable explanation",
  "embedding": [0.1, 0.2, 0.3, ...],
  "content_length": 245,
  "embedding_dimension": 1536,
  "created_at": "2024-08-21T10:30:00"
}
```

### Comparison Result
```json
{
  "clause_id": "uuid",
  "similarity_score": 0.92,
  "match_quality": "Excellent Match",
  "compliance_status": {
    "status": "Fully Compliant",
    "risk_level": "Low",
    "recommendations": ["No action required"]
  }
}
```
