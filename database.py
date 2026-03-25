from datetime import datetime
from typing import Optional, Dict, Any, List
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Atlas connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://YOUR_USERNAME:YOUR_PASSWORD@YOUR_CLUSTER.mongodb.net/?retryWrites=true&w=majority")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "Deltaplus_checkscanner")

class MongoDB:
    def __init__(self):
        self.client = None
        self.db = None
        self.connect()
    
    def connect(self):
        try:
            self.client = MongoClient(MONGO_URI)
            self.db = self.client[MONGO_DB_NAME]
            # Test connection
            self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB Atlas database: {MONGO_DB_NAME}")
            self._create_indexes()
        except Exception as e:
            logger.error(f"MongoDB connection error: {e}")
            raise
    
    def _create_indexes(self):
        try:
            self.db.users.create_index("username", unique=True)
            self.db.checks.create_index("user_id")
            self.db.checks.create_index("check_no")
            self.db.checks.create_index("created_at", DESCENDING)
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
    
    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

# Global database instance
db_instance = MongoDB()

def get_db():
    try:
        return db_instance.db
    except Exception as e:
        logger.error(f"Error getting database connection: {e}")
        raise

def serialize_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

def serialize_documents(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_document(doc) for doc in docs]

class User:
    @staticmethod
    def create(db, username: str, full_name: str, password_hash: str) -> Dict[str, Any]:
        user = {
            "username": username,
            "full_name": full_name,
            "password_hash": password_hash,
            "created_at": datetime.utcnow()
        }
        try:
            result = db.users.insert_one(user)
            user["_id"] = result.inserted_id
            return user
        except DuplicateKeyError:
            raise ValueError("Username already exists")
    
    @staticmethod
    def find_by_username(db, username: str) -> Optional[Dict[str, Any]]:
        return db.users.find_one({"username": username})
    
    @staticmethod
    def find_by_id(db, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            return db.users.find_one({"_id": ObjectId(user_id)})
        except:
            return None

class CheckRecord:
    @staticmethod
    def create(db, check_data: Dict[str, Any]) -> Dict[str, Any]:
        check = {
            "user_id": check_data.get("user_id"),
            "user_full_name": check_data.get("user_full_name"),
            "account_no": check_data.get("account_no"),
            "account_name": check_data.get("account_name"),
            "pay_to_the_order_of": check_data.get("pay_to_the_order_of"),
            "check_no": check_data.get("check_no"),
            "amount": check_data.get("amount"),
            "bank_name": check_data.get("bank_name"),
            "date": check_data.get("date"),
            "image_url": check_data.get("image_url"),
            "is_received": check_data.get("is_received", False),
            "received_date": check_data.get("received_date"),
            "received_by": check_data.get("received_by"),
            "cr": check_data.get("cr"),
            "cr_date": check_data.get("cr_date"),
            "date_deposited": check_data.get("date_deposited"),
            "bank_deposited": check_data.get("bank_deposited"),
            "deposited_by": check_data.get("deposited_by"),
            "created_at": datetime.utcnow()
        }
        
        result = db.checks.insert_one(check)
        check["_id"] = result.inserted_id
        return check
    
    @staticmethod
    def find_by_id(db, check_id: str) -> Optional[Dict[str, Any]]:
        try:
            return db.checks.find_one({"_id": ObjectId(check_id)})
        except:
            return None
    
    @staticmethod
    def find_by_check_no(db, check_no: str) -> Optional[Dict[str, Any]]:
        return db.checks.find_one({"check_no": check_no})
    
    @staticmethod
    def get_all(db) -> List[Dict[str, Any]]:
        return list(db.checks.find().sort("created_at", DESCENDING))
    
    @staticmethod
    def update(db, check_id: str, update_data: Dict[str, Any]) -> bool:
        try:
            result = db.checks.update_one(
                {"_id": ObjectId(check_id)},
                {"$set": update_data}
            )
            return result.modified_count > 0
        except:
            return False
    
    @staticmethod
    def delete(db, check_id: str) -> bool:
        try:
            result = db.checks.delete_one({"_id": ObjectId(check_id)})
            return result.deleted_count > 0
        except:
            return False