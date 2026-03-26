import os
import asyncio
import logging
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
import requests
import cloudinary
import cloudinary.uploader

from extractor import extract_fields, validate_check_data
from database import get_db, User, CheckRecord, serialize_document, serialize_documents

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Philippine Check Scanner API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")

API_KEY = os.getenv("OCR_SPACE_API_KEY", "K87517634688957")

cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
api_key = os.getenv("CLOUDINARY_API_KEY")
api_secret = os.getenv("CLOUDINARY_API_SECRET")
if cloud_name and api_key and api_secret:
    cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)
    logger.info("Cloudinary configured successfully")
else:
    logger.warning("Cloudinary credentials missing")

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ========== Database ==========
def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

async def authenticate_user(db, username: str, password: str):
    user = User.find_by_username(db, username)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = User.find_by_username(db, username)
    if user is None:
        raise credentials_exception
    return user

# ========== Notifications ==========
notification_queues = []
MAX_NOTIFICATIONS = 500
notifications = []

def add_notification(user_name: str, check_id: str, action: str = "new_check"):
    timestamp = datetime.now()
    notification = {
        "id": len(notifications) + 1,
        "message": f"New check received from {user_name} (Check #{check_id})",
        "user_name": user_name,
        "check_id": check_id,
        "action": action,
        "timestamp": timestamp.isoformat(),
        "read": False
    }
    notifications.insert(0, notification)
    while len(notifications) > MAX_NOTIFICATIONS:
        notifications.pop()
    
    for q in notification_queues:
        try:
            q.put_nowait(notification)
        except asyncio.QueueFull:
            pass

@app.get("/api/notifications/stream")
async def notifications_stream():
    async def event_generator():
        queue = asyncio.Queue()
        notification_queues.append(queue)
        try:
            while True:
                notification = await queue.get()
                yield f"data: {json.dumps(notification)}\n\n"
        except asyncio.CancelledError:
            notification_queues.remove(queue)
            raise
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.put("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: int):
    for n in notifications:
        if n["id"] == notification_id:
            n["read"] = True
            return {"success": True}
    raise HTTPException(status_code=404, detail="Notification not found")

@app.delete("/api/notifications/clear")
async def clear_notifications():
    global notifications
    notifications = []
    return {"success": True, "message": "All notifications cleared"}

@app.get("/api/notifications/history")
async def get_notification_history(limit: int = 100):
    return notifications[:limit]

@app.get("/api/notifications")
async def get_notifications():
    return notifications

@app.get("/api/notifications/unread-count")
async def get_unread_count():
    unread = sum(1 for n in notifications if not n["read"])
    return {"unread": unread}

@app.put("/api/notifications/mark-read")
async def mark_notifications_read():
    for n in notifications:
        n["read"] = True
    return {"success": True}

# ========== Public endpoints ==========
@app.get("/api/checks")
async def get_checks(db = Depends(get_db)):
    checks = CheckRecord.get_all(db)
    return serialize_documents(checks)

# ========== Auth endpoints ==========
@app.post("/register")
async def register(
    username: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    db = Depends(get_db)
):
    existing = User.find_by_username(db, username)
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed = get_password_hash(password)
    user = User.create(db, username, full_name, hashed)
    return {"message": "User created successfully", "user_id": str(user["_id"])}

# Fixed login endpoint without OAuth2PasswordRequestForm
@app.post("/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    db = Depends(get_db)
):
    user = await authenticate_user(db, username, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(data={"sub": user["username"]}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": token, "token_type": "bearer", "full_name": user["full_name"]}

# ========== Scan endpoints ==========
@app.post("/scan-check")
async def scan_check(file: UploadFile = File(...)):
    try:
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/tiff']
        if file.content_type not in allowed_types:
            raise HTTPException(status_code=400, detail=f"Unsupported image type. Allowed: {allowed_types}")
        
        image = await file.read()
        logger.info(f"Processing image: {file.filename}, Size: {len(image)} bytes")
        
        max_retries = 2
        timeout = 60
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Sending to OCR.space API (attempt {attempt+1}/{max_retries+1})...")
                response = requests.post(
                    "https://api.ocr.space/parse/image",
                    files={"file": (file.filename, image, file.content_type)},
                    data={
                        "apikey": API_KEY,
                        "language": "eng",
                        "isOverlayRequired": False,
                        "detectOrientation": True,
                        "scale": True,
                        "OCREngine": "2",
                        "filetype": file.content_type.split('/')[-1]
                    },
                    timeout=timeout
                )
                break
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise HTTPException(status_code=504, detail="OCR service timeout")
        
        result = response.json()
        if result.get("IsErroredOnProcessing"):
            error_msg = result.get("ErrorMessage", ["Unknown OCR error"])[0]
            raise HTTPException(status_code=500, detail=f"OCR processing failed: {error_msg}")
        if "ParsedResults" not in result or not result["ParsedResults"]:
            raise HTTPException(status_code=500, detail="No text extracted")
        
        parsed_text = result["ParsedResults"][0]["ParsedText"]
        extracted_data = extract_fields(parsed_text)
        validation = validate_check_data(extracted_data)
        
        logger.info("Extracted fields:")
        for key, value in extracted_data.items():
            logger.info(f"  {key}: {value}")
        
        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "data": extracted_data,
            "validation": validation,
            "ocr_confidence": result["ParsedResults"][0].get("FileParseExitCode", 0)
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

@app.post("/scan-check-debug")
async def scan_check_debug(file: UploadFile = File(...)):
    try:
        image = await file.read()
        response = requests.post(
            "https://api.ocr.space/parse/image",
            files={"file": (file.filename, image, file.content_type)},
            data={"apikey": API_KEY, "language": "eng", "OCREngine": "2"},
            timeout=60
        )
        result = response.json()
        if not result.get("IsErroredOnProcessing"):
            parsed_text = result["ParsedResults"][0]["ParsedText"]
            return JSONResponse({
                "success": True,
                "raw_text": parsed_text,
                "extracted": extract_fields(parsed_text)
            })
        else:
            return JSONResponse({
                "success": False,
                "error": result.get("ErrorMessage", ["Unknown error"])
            })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/save-check")
async def save_check(
    check_data: str = Form(...),
    image: UploadFile = File(...),
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        data = json.loads(check_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid check_data JSON")

    if not data.get("check_no"):
        raise HTTPException(status_code=400, detail="Check number is required")

    # Check for duplicate check number
    existing = CheckRecord.find_by_check_no(db, data["check_no"])
    if existing:
        raise HTTPException(status_code=400, detail="Check number already exists")

    try:
        image_bytes = await image.read()
        upload_result = cloudinary.uploader.upload(
            image_bytes,
            folder="check_scans",
            public_id=f"check_{data.get('check_no', 'unknown')}"
        )
        image_url = upload_result.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary upload error: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload image")

    check_record = {
        "user_id": str(current_user["_id"]),
        "user_full_name": current_user["full_name"],
        "account_no": data.get("account_no"),
        "account_name": data.get("account_name"),
        "pay_to_the_order_of": data.get("pay_to_the_order_of"),
        "check_no": data.get("check_no"),
        "amount": data.get("amount"),
        "bank_name": data.get("bank_name"),
        "date": data.get("date"),
        "image_url": image_url,
        "is_received": data.get("is_received", False),
        "received_date": data.get("received_date"),
        "received_by": data.get("received_by"),
        "cr": data.get("cr"),
        "cr_date": data.get("cr_date"),
        "date_deposited": data.get("date_deposited"),
        "bank_deposited": data.get("bank_deposited"),
        "deposited_by": data.get("deposited_by")
    }
    
    saved_check = CheckRecord.create(db, check_record)
    check_id = str(saved_check["_id"])

    add_notification(current_user["full_name"], check_id)

    return {
        "success": True,
        "message": "Check saved successfully",
        "id": check_id,
        "image_url": image_url
    }

# ========== Management endpoints ==========
@app.put("/api/checks/{check_id}")
async def update_check(check_id: str, update_data: dict, db = Depends(get_db)):
    check = CheckRecord.find_by_id(db, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    allowed_fields = ["account_name", "pay_to_the_order_of", "amount", "date", "cr", "cr_date", 
                      "date_deposited", "bank_deposited", "received_by", "deposited_by"]
    filtered_update = {}
    for field in allowed_fields:
        if field in update_data:
            filtered_update[field] = update_data[field]
    if CheckRecord.update(db, check_id, filtered_update):
        return {"success": True, "message": "Check updated"}
    raise HTTPException(status_code=500, detail="Update failed")

@app.delete("/api/checks/{check_id}")
async def delete_check(check_id: str, db = Depends(get_db)):
    check = CheckRecord.find_by_id(db, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    if CheckRecord.delete(db, check_id):
        return {"success": True, "message": "Check deleted"}
    raise HTTPException(status_code=500, detail="Delete failed")

@app.put("/api/checks/{check_id}/received")
async def mark_received(
    check_id: str,
    received_date: str = Form(...),
    received_by: str = Form(...),
    db = Depends(get_db)
):
    check = CheckRecord.find_by_id(db, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    if CheckRecord.update(db, check_id, {
        "is_received": True,
        "received_date": received_date,
        "received_by": received_by
    }):
        return {"success": True, "message": "Check marked as received"}
    raise HTTPException(status_code=500, detail="Update failed")

@app.put("/api/checks/{check_id}/unreceived")
async def mark_unreceived(check_id: str, db = Depends(get_db)):
    check = CheckRecord.find_by_id(db, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Check not found")
    if CheckRecord.update(db, check_id, {
        "is_received": False,
        "received_date": None,
        "received_by": None
    }):
        return {"success": True, "message": "Check unmarked"}
    raise HTTPException(status_code=500, detail="Update failed")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db = Depends(get_db)):
    checks = CheckRecord.get_all(db)
    return templates.TemplateResponse("dashboard.html", {"request": request, "checks": serialize_documents(checks)})

@app.get("/")
async def root():
    return {
        "message": "Philippine Check Scanner API",
        "version": "2.0.0",
        "database": "MongoDB Atlas",
        "database_name": "Deltaplus_checkscanner",
        "status": "running",
        "extracted_fields": ["account_no", "account_name", "pay_to_the_order_of", "check_no", "amount", "bank_name", "date"]
    }

@app.get("/health")
async def health_check(db = Depends(get_db)):
    try:
        db.command('ping')
        return {"status": "healthy", "timestamp": datetime.now().isoformat(), "database": "connected"}
    except:
        return {"status": "unhealthy", "timestamp": datetime.now().isoformat(), "database": "disconnected"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)