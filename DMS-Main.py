from datetime import datetime
from bson import ObjectId
from fastapi import FastAPI, HTTPException, status, UploadFile
from pathlib import Path
from pymongo import MongoClient
from pydantic import BaseModel
from typing import List

# Create a FastAPI instance
dms = FastAPI()

# Initialize the MongoDB client
client = MongoClient()

# Connect to the "Document_Management_System" database
db = client.Document_Management_System

# Get the "user_records" and "documents" collections from the database
users = db.user_records
documents = db.documents


# Define the Pydantic model for the basic information of a user
class BasicsOfAUser(BaseModel):
    Name: str
    Designation: str
    Office: str
    Email: str
    Password: str


# Define the Pydantic model for the input payload to add multiple users
class InputUser(BaseModel):
    List_Of_User: List[BasicsOfAUser]


# Define a GET endpoint at the root URL ("/") to list all database names (for testing purposes)
@dms.get("/")
def get_everything():
    x = client.list_database_names()
    print(x)


#
# Define a GET endpoint to retrieve all users from the "user_records" collection
@dms.get("/users/")
async def get_users():
    users_list = list(users.find())
    for user in users_list:
        user['_id'] = str(user['_id'])
    return {"users": users_list}


# Define a POST endpoint to add multiple users to the "user_records" collection
@dms.post("/users/add", status_code=status.HTTP_201_CREATED)
def add_users(post: InputUser):
    list_of_user = post.dict()
    for x in list_of_user.values():
        users.insert_many(x)
    return post


# Define a POST endpoint to upload a file to the server
@dms.post("/files/upload/")
async def create_upload_file(file: UploadFile):
    file_path = Path.cwd() / "Documents" / file.filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())
    upload_time = datetime.now()
    result = documents.insert_one({"file_path": str(file_path), "upload_time": upload_time})
    return {"document_id": str(result.inserted_id), "filename": file.filename}


# Define a GET endpoint to retrieve all documents from the "documents" collection
@dms.get("/files/")
async def get_files():
    files = list(documents.find())
    for file in files:
        file['_id'] = str(file['_id'])
    return {"files": files}


# Define a DELETE endpoint to delete a file from the server and the "documents" collection
@dms.delete("/files/delete/{filename}")
async def delete_file(filename: str):
    file_path = Path.cwd() / "Documents" / filename
    if file_path.exists():
        file_path.unlink()
        documents.delete_one({"file_path": str(file_path)})
        return {"detail": f"Deleted {filename}"}
    else:
        return {"detail": f"{filename} not found"}


# Define a POST endpoint to associate a document with a user
@dms.post("/associate/{document_id}/{user_id}")
async def associate_document_with_user(document_id: str, user_id: str):
    document = documents.find_one({"_id": ObjectId(document_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get the current maximum priority number for this document
    max_priority = 0
    for associated_user in document.get("associated_users", []):
        if associated_user["priority"] > max_priority:
            max_priority = associated_user["priority"]

    # Increment the priority number for the new association
    priority = max_priority + 1

    # Update the document to add the new associated user
    documents.update_one({"_id": ObjectId(document_id)},
                         {"$push": {
                             "associated_users": {"user_id": user_id, "approval_status": False, "priority": priority}}})

    return {"detail": f"Associated document {document_id} with user {user_id}"}


# Define a GET endpoint to retrieve all associated users of a document
@dms.get("/associated_users/{document_id}")
async def get_associated_users(document_id: str):
    document = documents.find_one({"_id": (ObjectId(document_id))})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    associated_users = []

    for user in document.get("associated_users", []):
        user_record = users.find_one({"_id": ObjectId(user["user_id"])})
        if user_record:
            # Convert ObjectId to string
            user_record["_id"] = str(user_record["_id"])
            associated_users.append({"user": user_record, "approval_status": user["approval_status"]})

    return {"associated_users": associated_users}


# Define a POST endpoint to approve a document for a user
@dms.post("/approve/{document_id}/{user_id}")
async def approve_document(document_id: str, user_id: str):
    document = documents.find_one({"_id": ObjectId(document_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    associated_users = document.get("associated_users", [])

    # Update the approval status for the specified user in the document
    for i in range(len(associated_users)):
        if associated_users[i]["user_id"] == user_id:
            associated_users[i]["approval_status"] = True

    documents.update_one({"_id": ObjectId(document_id)}, {"$set": {"associated_users": associated_users}})

    return {"detail": f"Approved document {document_id} for user {user_id}"}


# Define a GET endpoint to retrieve all documents associated with a user
@dms.get("/associated_documents/{user_id}")
async def get_associated_documents(user_id: str):
    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    associated_documents = []

    for document in documents.find({"associated_users.user_id": user_id}):
        # Find the current user's priority for this document
        current_user_priority = None
        for associated_user in document["associated_users"]:
            if associated_user["user_id"] == user_id:
                current_user_priority = associated_user["priority"]
                break

        # Check if all associated users with a lower priority have an approval_status of True
        all_approved = True
        for associated_user in document["associated_users"]:
            if associated_user["priority"] < current_user_priority and not associated_user["approval_status"]:
                all_approved = False
                break

        if all_approved:
            # Convert ObjectId to string
            document["_id"] = str(document["_id"])
            associated_documents.append(document)

    return {"associated_documents": associated_documents}


# Define a DELETE endpoint to disassociate a document from a user
@dms.delete("/disassociate/{document_id}/{user_id}")
async def disassociate_document_from_user(document_id: str, user_id: str):
    document = documents.find_one({"_id": ObjectId(document_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    associated_users = document.get("associated_users", [])

    # Remove the specified user from the associated_users list
    for i in range(len(associated_users)):
        if associated_users[i]["user_id"] == user_id:
            del associated_users[i]
            break

    documents.update_one({"_id": ObjectId(document_id)}, {"$set": {"associated_users": associated_users}})

    return {"detail": f"Disassociated document {document_id} from user {user_id}"}
