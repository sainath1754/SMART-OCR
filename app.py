"""
IntelliScan - Intelligent OCR & Document Understanding System
A production-ready Flask application for OCR, entity extraction, and document processing

Author: Your Name
Version: 1.0.0
License: MIT
"""

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import os
import json
import re
from datetime import datetime
import uuid
import traceback
import platform

# Initialize Flask application
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret-key-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['HISTORY_FOLDER'] = 'history'

# Create necessary folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['HISTORY_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'tiff', 'bmp'}

# Windows-specific configuration
if platform.system() == 'Windows':
    print("\n🪟 Windows detected - Configuring paths...")
    
    # Try to find Tesseract
    tesseract_paths = [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        r'D:\Tesseract-OCR\tesseract.exe',
        os.path.join(os.getcwd(), 'tesseract', 'tesseract.exe')
    ]
    
    # Try to find Poppler
    poppler_paths = [
        r'C:\poppler\Library\bin',
        r'C:\poppler-24.08.0\Library\bin',
        r'D:\poppler\Library\bin',
        os.path.join(os.getcwd(), 'poppler', 'Library', 'bin')
    ]

# Try to import OCR libraries with fallback
try:
    import pytesseract
    from PIL import Image
    
    # Configure Tesseract path for Windows
    if platform.system() == 'Windows':
        tesseract_found = False
        for path in tesseract_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                print(f"✓ Tesseract found at: {path}")
                tesseract_found = True
                break
        
        if not tesseract_found:
            print("⚠️  Tesseract not found at common locations")
            print("   Please install from: https://github.com/UB-Mannheim/tesseract/wiki")
            print("   Or set path manually in app.py")
    
    OCR_AVAILABLE = True
    print("✓ Tesseract OCR loaded successfully")
except ImportError as e:
    OCR_AVAILABLE = False
    print(f"✗ OCR libraries not available: {e}")

try:
    import pdf2image
    
    # Configure Poppler path for Windows
    if platform.system() == 'Windows':
        poppler_found = False
        for path in poppler_paths:
            if os.path.exists(path):
                os.environ['PATH'] = path + os.pathsep + os.environ.get('PATH', '')
                print(f"✓ Poppler found at: {path}")
                poppler_found = True
                break
        
        if not poppler_found:
            print("⚠️  Poppler not found at common locations")
            print("   Please install from: https://github.com/oschwartz10612/poppler-windows")
            print("   Or set path manually in app.py")
    
    PDF_AVAILABLE = True
    print("✓ PDF processing loaded successfully")
except ImportError as e:
    PDF_AVAILABLE = False
    print(f"✗ PDF processing not available: {e}")


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class EntityExtractor:
    """Extract structured entities from text using regex patterns"""
    
    @staticmethod
    def extract_emails(text):
        """Extract email addresses from text"""
        pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return list(set(re.findall(pattern, text)))
    
    @staticmethod
    def extract_phones(text):
        """Extract phone numbers from text (multiple formats)"""
        patterns = [
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # 123-456-7890 or 1234567890
            r'\b\(\d{3}\)\s*\d{3}[-.]?\d{4}\b',  # (123) 456-7890
            r'\b\+\d{1,3}\s?\d{1,14}\b'  # +1 234567890 (international)
        ]
        phones = []
        for pattern in patterns:
            phones.extend(re.findall(pattern, text))
        return list(set(phones))
    
    @staticmethod
    def extract_dates(text):
        """Extract dates from text (multiple formats)"""
        patterns = [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',  # 12/31/2024 or 12-31-24
            r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',  # 2024-12-31
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b'  # January 1, 2024
        ]
        dates = []
        for pattern in patterns:
            dates.extend(re.findall(pattern, text, re.IGNORECASE))
        return list(set(dates))
    
    @staticmethod
    def extract_amounts(text):
        """Extract monetary amounts from text"""
        pattern = r'\$\s?\d+(?:,\d{3})*(?:\.\d{2})?|\d+(?:,\d{3})*(?:\.\d{2})?\s?(?:USD|INR|EUR|GBP|dollars?|rupees?)'
        return list(set(re.findall(pattern, text, re.IGNORECASE)))
    
    @staticmethod
    def extract_urls(text):
        """Extract URLs from text"""
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        return list(set(re.findall(pattern, text)))
    
    @staticmethod
    def extract_all(text):
        """Extract all entity types from text"""
        return {
            'emails': EntityExtractor.extract_emails(text),
            'phones': EntityExtractor.extract_phones(text),
            'dates': EntityExtractor.extract_dates(text),
            'amounts': EntityExtractor.extract_amounts(text),
            'urls': EntityExtractor.extract_urls(text)
        }


class DocumentProcessor:
    """Process documents with OCR and layout analysis"""
    
    @staticmethod
    def process_image(image_path):
        """Extract text from image using Tesseract OCR"""
        if not OCR_AVAILABLE:
            raise Exception("OCR libraries not installed. Please install pytesseract and Pillow.")
        
        try:
            print(f"Processing image: {image_path}")
            
            # Open and process image
            img = Image.open(image_path)
            print(f"Image opened: {img.size}, mode: {img.mode}")
            
            # Convert to RGB if necessary
            if img.mode not in ['RGB', 'L']:
                print(f"Converting image from {img.mode} to RGB")
                img = img.convert('RGB')
            
            # Perform OCR
            print("Running Tesseract OCR...")
            text = pytesseract.image_to_string(img)
            print(f"OCR extracted {len(text)} characters")
            
            # Get detailed data for confidence
            try:
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            except Exception as e:
                print(f"Warning: Could not calculate confidence: {e}")
                avg_confidence = 0
            
            return {
                'text': text,
                'confidence': round(avg_confidence, 2),
                'word_count': len(text.split()),
                'char_count': len(text)
            }
            
        except Exception as e:
            print(f"Error in process_image: {str(e)}")
            print(traceback.format_exc())
            raise Exception(f"OCR processing failed: {str(e)}")
    
    @staticmethod
    def process_pdf(pdf_path):
        """Convert PDF to images and extract text from each page"""
        if not PDF_AVAILABLE:
            raise Exception("PDF processing libraries not installed. Please install pdf2image and poppler.")
        
        if not OCR_AVAILABLE:
            raise Exception("OCR libraries not installed. Please install pytesseract and Pillow.")
        
        try:
            print(f"Processing PDF: {pdf_path}")
            
            # Convert PDF to images with error handling
            try:
                print("Converting PDF to images...")
                images = pdf2image.convert_from_path(
                    pdf_path, 
                    dpi=200,  # Lower DPI for faster processing
                    fmt='jpeg',
                    thread_count=2
                )
                print(f"Successfully converted {len(images)} pages")
            except Exception as e:
                print(f"PDF conversion error: {str(e)}")
                # Try alternative method
                print("Trying alternative PDF conversion method...")
                images = pdf2image.convert_from_path(pdf_path, dpi=150)
            
            if not images:
                raise Exception("No pages found in PDF")
            
            all_text = []
            total_confidence = 0
            
            # Process each page
            for i, image in enumerate(images):
                print(f"Processing page {i+1}/{len(images)}...")
                
                # Extract text
                text = pytesseract.image_to_string(image)
                
                # Get confidence
                try:
                    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
                    confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                    page_confidence = sum(confidences) / len(confidences) if confidences else 0
                except:
                    page_confidence = 0
                
                # Add page header and text
                all_text.append(f"--- Page {i+1} ---\n{text}")
                total_confidence += page_confidence
            
            # Combine all pages
            combined_text = "\n\n".join(all_text)
            avg_confidence = total_confidence / len(images) if images else 0
            
            print(f"PDF processing complete: {len(images)} pages, {len(combined_text)} characters")
            
            return {
                'text': combined_text,
                'confidence': round(avg_confidence, 2),
                'word_count': len(combined_text.split()),
                'char_count': len(combined_text),
                'page_count': len(images)
            }
            
        except Exception as e:
            print(f"Error in process_pdf: {str(e)}")
            print(traceback.format_exc())
            raise Exception(f"PDF processing failed: {str(e)}")


class HistoryManager:
    """Manage processing history with persistent JSON storage"""
    
    @staticmethod
    def save_result(filename, result, entities):
        """Save processing result to history"""
        history_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()
        
        history_entry = {
            'id': history_id,
            'filename': filename,
            'timestamp': timestamp,
            'result': result,
            'entities': entities
        }
        
        # Save to JSON file
        history_file = os.path.join(app.config['HISTORY_FOLDER'], f'{history_id}.json')
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history_entry, f, indent=2, ensure_ascii=False)
        
        print(f"Saved to history: {history_id}")
        return history_id
    
    @staticmethod
    def get_all_history():
        """Retrieve all history entries"""
        history = []
        
        # Read all JSON files in history folder
        for filename in os.listdir(app.config['HISTORY_FOLDER']):
            if filename.endswith('.json'):
                filepath = os.path.join(app.config['HISTORY_FOLDER'], filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        history.append(json.load(f))
                except Exception as e:
                    print(f"Error reading {filename}: {e}")
                    continue
        
        # Sort by timestamp, newest first
        history.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return history
    
    @staticmethod
    def get_history_item(history_id):
        """Retrieve specific history entry by ID"""
        filepath = os.path.join(app.config['HISTORY_FOLDER'], f'{history_id}.json')
        
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return None
    
    @staticmethod
    def delete_history_item(history_id):
        """Delete history entry by ID"""
        filepath = os.path.join(app.config['HISTORY_FOLDER'], f'{history_id}.json')
        
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        
        return False


# ============================================================
# ROUTES
# ============================================================

@app.route('/')
def index():
    """Main page - render the frontend"""
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and OCR processing"""
    filepath = None
    
    try:
        print("\n=== Upload Request Received ===")
        
        # Check if file is in request
        if 'file' not in request.files:
            print("Error: No file in request")
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        print(f"File received: {file.filename}")
        
        # Check if file is selected
        if file.filename == '':
            print("Error: Empty filename")
            return jsonify({'error': 'No file selected'}), 400
        
        # Check if file type is allowed
        if not allowed_file(file.filename):
            print(f"Error: Invalid file type: {file.filename}")
            return jsonify({
                'error': 'Invalid file type. Allowed types: PNG, JPG, JPEG, PDF, TIFF, BMP'
            }), 400
        
        # Check if OCR is available
        if not OCR_AVAILABLE:
            return jsonify({
                'error': 'OCR system not configured. Please contact administrator.'
            }), 500
        
        # Secure the filename
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Save uploaded file temporarily
        print(f"Saving file to: {filepath}")
        file.save(filepath)
        
        # Verify file was saved
        if not os.path.exists(filepath):
            raise Exception("File save failed")
        
        file_size = os.path.getsize(filepath)
        print(f"File saved successfully: {file_size} bytes")
        
        # Process based on file type
        file_ext = filename.rsplit('.', 1)[1].lower()
        print(f"Processing as: {file_ext}")
        
        if file_ext == 'pdf':
            if not PDF_AVAILABLE:
                return jsonify({
                    'error': 'PDF processing not available. Please upload an image instead.'
                }), 500
            result = DocumentProcessor.process_pdf(filepath)
        else:
            result = DocumentProcessor.process_image(filepath)
        
        print("Processing complete!")
        print(f"Extracted {result['word_count']} words")
        
        # Extract entities from the text
        entities = EntityExtractor.extract_all(result['text'])
        print(f"Entities extracted: {sum(len(v) for v in entities.values())} total")
        
        # Save to history
        history_id = HistoryManager.save_result(filename, result, entities)
        
        # Clean up uploaded file
        try:
            os.remove(filepath)
            print("Temporary file cleaned up")
        except Exception as e:
            print(f"Warning: Could not delete temp file: {e}")
        
        # Return successful response
        return jsonify({
            'success': True,
            'history_id': history_id,
            'result': result,
            'entities': entities
        })
    
    except Exception as e:
        # Log the full error
        print(f"\n!!! ERROR IN UPLOAD !!!")
        print(f"Error: {str(e)}")
        print(traceback.format_exc())
        
        # Clean up file if exists
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                print("Cleaned up file after error")
            except:
                pass
        
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500


@app.route('/history', methods=['GET'])
def get_history():
    """Get all processing history"""
    try:
        history = HistoryManager.get_all_history()
        return jsonify({
            'success': True,
            'history': history
        })
    except Exception as e:
        print(f"Error getting history: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/history/<history_id>', methods=['GET'])
def get_history_item(history_id):
    """Get specific history item by ID"""
    try:
        item = HistoryManager.get_history_item(history_id)
        
        if item:
            return jsonify({
                'success': True,
                'item': item
            })
        
        return jsonify({'error': 'History item not found'}), 404
    
    except Exception as e:
        print(f"Error getting history item: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/history/<history_id>', methods=['DELETE'])
def delete_history(history_id):
    """Delete history item by ID"""
    try:
        if HistoryManager.delete_history_item(history_id):
            return jsonify({'success': True})
        
        return jsonify({'error': 'History item not found'}), 404
    
    except Exception as e:
        print(f"Error deleting history: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/export/<history_id>', methods=['GET'])
def export_result(history_id):
    """Export result as JSON file"""
    try:
        item = HistoryManager.get_history_item(history_id)
        
        if item:
            return jsonify(item)
        
        return jsonify({'error': 'History item not found'}), 404
    
    except Exception as e:
        print(f"Error exporting: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    status = {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'ocr_available': OCR_AVAILABLE,
        'pdf_available': PDF_AVAILABLE
    }
    
    if OCR_AVAILABLE:
        try:
            version = pytesseract.get_tesseract_version()
            status['tesseract_version'] = str(version)
        except:
            status['tesseract_version'] = 'unknown'
    
    return jsonify(status), 200


# Error handlers
@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large error"""
    return jsonify({
        'error': 'File too large. Maximum size is 16MB'
    }), 413


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Resource not found'
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    print(f"500 Error: {error}")
    return jsonify({
        'error': 'Internal server error'
    }), 500


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("\n" + "="*60)
    print("IntelliScan OCR System Starting...")
    print("="*60)
    print(f"OCR Available: {OCR_AVAILABLE}")
    print(f"PDF Available: {PDF_AVAILABLE}")
    print(f"Upload Folder: {app.config['UPLOAD_FOLDER']}")
    print(f"History Folder: {app.config['HISTORY_FOLDER']}")
    print("="*60 + "\n")
    
    # Get port from environment variable (for cloud deployment)
    port = int(os.environ.get('PORT', 5000))
    
    # Run the application
    app.run(
        debug=os.environ.get('FLASK_ENV') != 'production',
        host='0.0.0.0',
        port=port,
        threaded=True
    )