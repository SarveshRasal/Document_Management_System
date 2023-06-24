import os
from datetime import datetime
from bson import ObjectId
from fastapi import FastAPI, HTTPException, status, UploadFile
from fastapi.middleware.cors import CORSMiddleware  # Import CORS middleware
from pathlib import Path
from pymongo import MongoClient
from pydantic import BaseModel
from typing import List, Optional

from starlette.responses import FileResponse

# Create a FastAPI instance
dms = FastAPI()

# Configure CORS settings
origins = [
    "http://localhost",
    "http://localhost:3000",
    "127.0.0.1:3000",  # Update with your Flutter app URL
]

dms.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],  # Add other allowed methods as necessary
    allow_headers=["*"],
)

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


# Define the Pydantic model for the login payload
class LoginCredentials(BaseModel):
    Email: str
    Password: str


class ApproveOrReject(BaseModel):
    document_id: str
    user_id: str
    approval_status: Optional[bool] = None


class Association(BaseModel):
    document_id: str
    user_id: str
    priority: int

# Define a POST endpoint to log in a current user and return his/her associated documents
@dms.post("/login/")
async def user_login(credentials: LoginCredentials):
    user = users.find_one({"Email": credentials.Email, "Password": credentials.Password})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user_id = str(user["_id"])
    associated_documents = await get_associated_documents(user_id)
    return {"user_id": user_id, "Email": credentials.Email, "Password": credentials.Password,
            "associated_documents": associated_documents}


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
async def associate_document_with_user(Association: Association):
    document = documents.find_one({"_id": ObjectId(Association.document_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    user = users.find_one({"_id": ObjectId(Association.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update the document to add the new associated user
    documents.update_one({"_id": ObjectId(Association.document_id)},
                         {"$push": {
                             "associated_users":
                                 {"user_id": Association.user_id,
                                  "approval_status": None,
                                  "priority": Association.priority}}})

    return {"detail": f"Associated document {Association.document_id} with user {Association.user_id}"}


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
            user_record["approval_status"] = user["approval_status"]
            user_record["priority"] = user["priority"]
            associated_users.append(user_record)

    return {"associated_users": associated_users}


# Define a POST endpoint to approve a document for a user
@dms.post("/status/{document_id}/{user_id}")
async def status(paylaod: ApproveOrReject):
    document = documents.find_one({"_id": ObjectId(paylaod.document_id)})
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    user = users.find_one({"_id": ObjectId(paylaod.user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    associated_users = document.get("associated_users", [])

    # Update the approval status for the specified user in the document
    for i in range(len(associated_users)):
        if associated_users[i]["user_id"] == paylaod.user_id:
            associated_users[i]["approval_status"] = paylaod.approval_status
            break

    documents.update_one({"_id": ObjectId(paylaod.document_id)}, {"$set": {"associated_users": associated_users}})

    # Notify the user who posted the document if the approval status is False
    # if not approval_status:
    #    notify_user(document_id)

    if paylaod.approval_status is True:
        return {"detail": f"Approved document {paylaod.document_id} for user {paylaod.user_id}"}
    elif paylaod.approval_status is False:
        return {"detail": f"Rejected document {paylaod.document_id} for user {paylaod.user_id}"}
    else:
        return {"detail": f"Reset approval status for document {paylaod.document_id} for user {paylaod.user_id}"}


# Define a GET endpoint to retrieve all documents associated with a user
# Define a GET endpoint to retrieve the documents associated with a user
@dms.get("/associated_documents/{user_id}")
async def get_associated_documents(user_id: str):
    user = users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    associated_documents = []

    # Find the documents associated with the user
    cursor = documents.find({"associated_users.user_id": user_id})
    for document in cursor:
        approval_status_list = []
        priority = None

        # Check the approval status and priority level for each associated user
        for user in document["associated_users"]:
            if user["user_id"] == user_id:
                approval_status = user.get("approval_status")
                priority = user.get("priority")
            else:
                if user.get("approval_status") is None:
                    approval_status_list.append(False)
                else:
                    approval_status_list.append(user.get("approval_status"))

        # Determine if the document should be included based on the priority and approval status
        if priority == 1 or all(approval_status_list):
            associated_documents.append({
                "document_id": str(document["_id"]),
                "file_path": document["file_path"],
                "approval_status": approval_status,
                "priority": priority
            })

    return {"user_id": user_id, "associated_documents": associated_documents}



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


# Define a GET endpoint to download a file by document ID
@dms.get("/files/download/{document_id}")
async def download_file(document_id: str):
    document = documents.find_one({"_id": ObjectId(document_id)})
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        file_path = document["file_path"]
        return FileResponse(file_path, media_type='application/pdf', filename=os.path.basename(file_path))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
