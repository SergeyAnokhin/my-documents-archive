"""Builds the nested folder tree for the Explorer-style browse view (GET /api/documents/tree).

Groups all non-deleted documents by the directory components of their path
relative to the library root, mirroring DocumentOut.relative_path.
"""
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Document
from ..schemas import FolderTreeDoc, FolderTreeNode


class _Node:
    __slots__ = ("name", "path", "folders", "documents")

    def __init__(self, name: str, path: str):
        self.name = name
        self.path = path
        self.folders: dict[str, "_Node"] = {}
        self.documents: list[Document] = []


def build_folder_tree(db: Session) -> FolderTreeNode:
    docs = db.query(Document).filter(Document.is_deleted == False).all()
    lib = Path(settings.library_path).resolve()

    root = _Node("", "")
    for doc in docs:
        try:
            rel = Path(doc.filepath).resolve().relative_to(lib)
        except ValueError:
            continue
        node = root
        for part in rel.parts[:-1]:
            child = node.folders.get(part)
            if child is None:
                child_path = f"{node.path}/{part}" if node.path else part
                child = _Node(part, child_path)
                node.folders[part] = child
            node = child
        node.documents.append(doc)

    return _to_schema(root)


def _to_schema(node: _Node) -> FolderTreeNode:
    folders = sorted(node.folders.values(), key=lambda n: n.name.lower())
    documents = sorted(node.documents, key=lambda d: d.filename.lower())
    children = [_to_schema(f) for f in folders]
    doc_count = len(documents)
    total_count = doc_count + sum(c.total_count for c in children)
    return FolderTreeNode(
        name=node.name,
        path=node.path,
        folders=children,
        documents=[FolderTreeDoc.model_validate(d) for d in documents],
        doc_count=doc_count,
        total_count=total_count,
    )
