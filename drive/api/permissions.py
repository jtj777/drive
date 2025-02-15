import frappe
from pypika import Order, Query, Table, Field, functions as fn
from frappe.utils.nestedset import rebuild_tree, get_ancestors_of
from drive.api.files import get_entity
from drive.api.files import get_doc_content
from drive.utils.files import get_user_directory
from drive.utils.user_group import get_entity_shared_with_user_groups
from drive.utils.users import mark_as_viewed


@frappe.whitelist()
def get_shared_with_list(entity_name):
    """
    Return the list of users with whom this file or folder has been shared

    :param entity_name: Document-name of this file or folder
    :raises PermissionError: If the user does not have edit permissions
    :return: List of users, with permissions and last modified datetime
    :rtype: list[frappe._dict]
    """

    if not frappe.has_permission(
        doctype="Drive Entity", doc=entity_name, ptype="write", user=frappe.session.user
    ):
        raise frappe.PermissionError

    entity_owner = frappe.db.get_value("Drive Entity", entity_name, "owner")

    users = frappe.db.get_all(
        "Drive DocShare",
        filters={
            "share_doctype": "Drive Entity",
            "share_name": entity_name,
            "user_doctype": "User",
            "user_name": ["not in", [frappe.session.user, entity_owner]],
            "everyone": 0,
            "public": 0,
        },
        order_by="name",
        fields=["user_name", "read", "write", "share"],
    )

    entity_owner_info = frappe.db.get_value(
        "User", entity_owner, ["user_image", "full_name", "email"], as_dict=True
    )
    for user in users:
        user_info = frappe.db.get_value(
            "User", user.user_name, ["user_image", "full_name"], as_dict=True
        )
        user.update(user_info)
    return {"owner": entity_owner_info, "users": users}


@frappe.whitelist()
def get_shared_user_group_list(entity_name):
    user_group_list = frappe.db.get_list(
        "Drive DocShare",
        filters={
            "share_doctype": "Drive Entity",
            "user_doctype": "User Group",
            "share_name": ["like", f"%{entity_name}%"],
        },
        fields=["user_name", "user_doctype", "read", "write"],
    )
    return user_group_list


@frappe.whitelist()
def get_shared_by_me(get_all=False, order_by="modified"):
    """
    Return the list of files and folders shared with the current user

    :param entity_name: Document-name of the folder whose contents are to be listed.
    :raises NotADirectoryError: If this DriveEntity doc is not a folder
    :return: List of DriveEntities with permissions
    :rtype: list[frappe._dict]
    """

    DriveDocShare = frappe.qb.DocType("Drive DocShare")
    DriveEntity = frappe.qb.DocType("Drive Entity")
    DriveFavourite = frappe.qb.DocType("Drive Favourite")
    DriveUser = frappe.qb.DocType("User")
    selectedFields = [
        DriveEntity.name,
        DriveEntity.title,
        DriveEntity.is_group,
        DriveUser.full_name,
        DriveUser.user_image,
        DriveEntity.owner,
        DriveEntity.modified,
        DriveEntity.creation,
        DriveEntity.file_size,
        DriveEntity.mime_type,
        DriveEntity.parent_drive_entity,
        DriveEntity.allow_comments,
        DriveEntity.color,
        DriveEntity.document,
        DriveEntity.allow_download,
        DriveDocShare.read,
        DriveDocShare.write,
        DriveDocShare.everyone,
        DriveDocShare.share,
        DriveFavourite.entity.as_("is_favourite"),
    ]

    query = (
        frappe.qb.from_(DriveEntity)
        .left_join(DriveDocShare)
        .on(
            (DriveDocShare.share_name == DriveEntity.name)
            & (DriveEntity.owner == frappe.session.user)
        )
        .left_join(DriveUser)
        .on((DriveEntity.owner == DriveUser.email))
        .left_join(DriveFavourite)
        .on(
            (DriveFavourite.entity == DriveEntity.name)
            & (DriveFavourite.user == frappe.session.user)
        )
        .select(*selectedFields)
        .where(
            (DriveEntity.is_active == 1)
            & (
                (DriveDocShare.user_name != frappe.session.user)
                | (DriveDocShare.everyone == 1)
                | (DriveDocShare.public == 1)
            )
        )
        .groupby(DriveEntity.name)
    )
    if get_all:
        return query.run(as_dict=True)

    result = query.orderby(
        order_by.split()[0],
        order=Order.desc if order_by.endswith("desc") else Order.asc,
    ).run(as_dict=True)
    names = [x.name for x in result]
    # Return highest level entity
    return filter(
        lambda x: x.parent_drive_entity not in names,
        result,
    )


@frappe.whitelist()
def get_shared_with_me(get_all=False, order_by="modified"):
    """
    Return the list of files and folders shared with the current user

    :param entity_name: Document-name of the folder whose contents are to be listed.
    :raises NotADirectoryError: If this DriveEntity doc is not a folder
    :return: List of DriveEntities with permissions
    :rtype: list[frappe._dict]
    """

    DocShare = frappe.qb.DocType("Drive DocShare")
    DriveEntity = frappe.qb.DocType("Drive Entity")
    DriveFavourite = frappe.qb.DocType("Drive Favourite")
    UserGroupMember = frappe.qb.DocType("User Group Member")
    selectedFields = [
        DriveEntity.name,
        DriveEntity.title,
        DriveEntity.is_group,
        DriveEntity.owner,
        DriveEntity.modified,
        DriveEntity.creation,
        DriveEntity.file_size,
        DriveEntity.mime_type,
        DriveEntity.parent_drive_entity,
        DriveEntity.allow_comments,
        DriveEntity.color,
        DriveEntity.document,
        DriveEntity.allow_download,
        DocShare.read,
        fn.Max(DocShare.write).as_("write"),
        DocShare.everyone,
        DocShare.share,
        DriveFavourite.entity.as_("is_favourite"),
    ]

    query = (
        frappe.qb.from_(DriveEntity)
        .inner_join(DocShare)
        .on((DocShare.share_name == DriveEntity.name))
        .left_join(UserGroupMember)
        .on((UserGroupMember.parent == DocShare.user_name))
        .left_join(DriveFavourite)
        .on(
            (DriveFavourite.entity == DriveEntity.name)
            & (DriveFavourite.user == frappe.session.user)
        )
        .groupby(DriveEntity.name)
        .select(*selectedFields)
        .where(
            (DriveEntity.is_active == 1)
            & (
                (UserGroupMember.user == frappe.session.user)
                | ((DocShare.user_name == frappe.session.user) | (DocShare.everyone == 1))
            )
        )
    )
    if get_all:
        return query.run(as_dict=True)

    result = query.orderby(
        order_by.split()[0],
        order=Order.desc if order_by.endswith("desc") else Order.asc,
    ).run(as_dict=True)
    names = [x.name for x in result]
    # Return highest level entity
    return filter(
        lambda x: x.parent_drive_entity not in names and x.owner != frappe.session.user,
        result,
    )


@frappe.whitelist()
def get_all_my_entities(fields=None):
    """
    Return file data with permissions

    :return: DriveEntity with permissions
    :rtype: frappe._dict
    """

    fields = fields or [
        "name",
        "title",
        "is_group",
        "owner",
        "modified",
        "file_size",
        "mime_type",
    ]
    my_entities = frappe.db.get_list(
        "Drive Entity",
        filters={
            "is_active": 1,
            "owner": frappe.session.user,
            "name": ["!=", get_user_directory().name],
        },
        fields=fields,
    )

    shared_entities = get_shared_with_me(get_all=True)

    all_entities = shared_entities + my_entities
    return list({x["name"]: x for x in all_entities}.values())


@frappe.whitelist(allow_guest=True)
def get_entity_with_permissions(entity_name):
    """
    Return file data with permissions

    :param entity_name: Name of file document.
    :raises IsADirectoryError: If this DriveEntity doc is not a file
    :return: DriveEntity with permissions
    :rtype: frappe._dict
    """

    fields = [
        "name",
        "title",
        "owner",
        "is_group",
        "is_active",
        "modified",
        "creation",
        "file_size",
        "mime_type",
        "file_ext",
        "allow_comments",
        "allow_download",
        "document",
    ]
    if not get_general_access(entity_name):
        if not frappe.has_permission(
            doctype="Drive Entity", doc=entity_name, ptype="read", user=frappe.session.user
        ):
            frappe.throw("Not permitted", frappe.PermissionError)

    entity = get_entity(entity_name, fields)
    entity_ancestors = get_ancestors_of("Drive Entity", entity)
    flag = False
    for z_entity_name in entity_ancestors:
        result = frappe.db.exists("Drive Entity", {"name": z_entity_name, "is_active": 0})
        if result:
            flag = True
            break
    if flag == True:
        frappe.throw("Parent Folder has been deleted")

    # Avoiding marking folders as recently viewed
    if frappe.session.user != "Guest":
        if not entity.is_group:
            mark_as_viewed(entity_name)
    # Add user group permission check on request
    if not entity.is_active:
        frappe.throw("Specified file has been trashed by the owner")

    if entity.owner == frappe.session.user:
        if entity.document:
            entity_doc_content = get_doc_content(entity.document)
            return entity | entity_doc_content
        return entity
    user_access = get_user_access(entity.name)
    if entity.document:
        entity_doc_content = get_doc_content(entity.document)
        return entity | user_access | entity_doc_content
    # print(user_access)
    return entity | user_access


@frappe.whitelist()
def get_general_access(entity_name):
    """
    Return the general access permissions for the given entity

    :param entity_name: Document-name of the entity whose permissions are to be fetched
    :return: Dict of general access permissions (read, write)
    :rtype: frappe._dict or None
    """
    DriveDocShare = frappe.qb.DocType("Drive DocShare")
    fields = [
        DriveDocShare.name,
        DriveDocShare.read,
        DriveDocShare.write,
        DriveDocShare.share,
        DriveDocShare.everyone,
        DriveDocShare.public,
    ]
    query = (
        frappe.qb.from_(DriveDocShare)
        .select(*fields)
        .where(
            (DriveDocShare.share_name == entity_name)
            & ((DriveDocShare.everyone == True) | (DriveDocShare.public == True))
        )
        .groupby(DriveDocShare.name)
    )
    return query.run(as_dict=True)


@frappe.whitelist()
def get_user_access(entity_name):
    """
    Return the user specific access permissions for an entity if it exists or general access permissions

    :param entity_name: Document-name of the entity whose permissions are to be fetched
    :return: Dict of general access permissions (read, write)
    :rtype: frappe._dict or None
    """

    if frappe.session.user != "Guest":
        user_access = frappe.db.get_value(
            "Drive DocShare",
            {
                "share_doctype": "Drive Entity",
                "share_name": entity_name,
                "user_doctype": "User",
                "user_name": frappe.session.user,
            },
            ["read", "write"],
            as_dict=1,
        )
        if user_access:
            return user_access
        group_access = user_group_entity_access(entity_name)
        if group_access:
            return group_access
        everyone_access = frappe.db.get_value(
            "Drive DocShare",
            {"share_name": entity_name, "everyone": 1},
            ["read", "write"],
            as_dict=1,
        )
        if everyone_access:
            return everyone_access
        public_access = frappe.db.get_value(
            "Drive DocShare",
            {"share_name": entity_name, "public": 1},
            ["read", "write"],
            as_dict=1,
        )
        if public_access:
            return public_access
    else:
        public_access = frappe.db.get_value(
            "Drive DocShare",
            {"share_name": entity_name, "public": 1},
            ["read", "write"],
            as_dict=1,
        )
        if public_access:
            return public_access
    return {"read": 0, "write": 0}


def user_group_entity_access(entity_name=None):
    """
    Get user group access level for current user and current entity

    :param entity_name: Document-name of the folder whose contents are to be listed. Defaults to the user directory
    :param order_by: Sort the list of results according to the specified field (eg: 'modified desc'). Defaults to 'title'
    :raises NotADirectoryError: If this DriveEntity doc is not a folder
    :raises PermissionError: If the user does not have access to the specified folder
    :return: List of DriveEntity records
    :rtype: list
    """

    DriveDocShare = frappe.qb.DocType("Drive DocShare")
    UserGroup = frappe.qb.DocType("User Group")
    UserGroupMember = frappe.qb.DocType("User Group Member")
    selectedFields = [
        DriveDocShare.user_name,
        DriveDocShare.read,
        DriveDocShare.write,
    ]

    query = (
        frappe.qb.from_(DriveDocShare)
        .join(UserGroupMember)
        .on((UserGroupMember.parent == DriveDocShare.user_name))
        .select(*selectedFields)
        .where(
            (DriveDocShare.share_name == entity_name)
            & (UserGroupMember.user == frappe.session.user)
        )
        .groupby(UserGroupMember.name)
    )
    result = query.run(as_dict=True)
    if not result:
        return False
    max_read = max(d["read"] for d in result)
    max_write = max(d["write"] for d in result)
    return {"read": max_read, "write": max_write}
