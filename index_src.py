from flask import Flask
import pymongo
from pymongo import MongoClient
from bson.json_util import dumps
from flask_cors import CORS
from bson.objectid import ObjectId
from flask import request
from pymongo import ReturnDocument
from secret import get_secret
import re
from tld import get_tld
import requests as r
import simplejson as json
import dns.resolver

from flask_jwt_extended import JWTManager, jwt_required,\
    create_access_token, get_jwt_identity

app = Flask(__name__)
app.secret_key = get_secret()
jwt = JWTManager(app)

CORS(app,automatic_options=False)
client = MongoClient('mongodb://localhost:27017/')
db = client.src_index
site_collection = db.NewSites
user_collection = db.Users

@app.route('/sites/search', methods = ['POST'])
def hybridSearch():
    findObject = {}

    query = request.get_json()
    query_page_size = query.get('page_size')
    query_page = query.get('page')
    query_groups = query.get('groups')
    query_owned = query.get('owned')
    query_domain = query.get('domain')
    query_keyword = query.get('keyword')
    query_sort = query.get('sort')


    if query_page_size is None or query_page_size<=0 :
        page_size = 50
    else :
        page_size = query_page_size

    if query_page is None or query_page<0 :
        page = 0
    else :
        page = query['page']

    skip = page_size * page

    if query_groups is not None and query_groups!='全部':
        findObject['groups'] = query_groups


    if query_owned is not None and query_owned is True:
        findObject['owned'] = True

    findObject['$and'] = []
    if query_domain is not None:
        if query_domain[0] != u'others':
            orObj = {'$or':[]}
            for suffix in query_domain:
                orObj['$or'].append({"url":{"$regex":'\\'+suffix}})
            if len(orObj['$or'])>0:
                findObject['$and'].append(orObj)
        else:
            andObj = {'$and':[]}
            for i in range(1,len(query_domain)):
                regexStr = '\\' + query_domain[i]
                andObj['$and'].append({"url":{'$not' :re.compile(regexStr)}})
            if len(andObj['$and'])>0:
                findObject['$and'].append(andObj)


    if query_keyword is not None:
        orObj = {'$or':[{'title':query['keyword']}
            ,{'url':query['keyword']}
            ,{'meta.description':query['keyword']}
            ,{'meta.keywords':query['keyword']}
            ,{'meta.author':query['keyword']}]}
        if len(orObj['$or'])>0:
            findObject['$and'].append(orObj)

    if len(findObject['$and'])<1:
        del findObject['$and']

    cursor = site_collection.find(findObject).skip(skip).limit(page_size)
    if query_sort is not None and len(query_sort)>0:
        query_sort_tupple = []
        for e in query_sort:
            for k in e.items():
                query_sort_tupple.append(k)
        query_sort_tupple.append(('owned', pymongo.DESCENDING))
        query_sort_tupple.append(('createdAt', pymongo.DESCENDING))

        cursor = cursor.sort(query_sort_tupple)


    count = int(cursor.count() / page_size)
    res = {"pages":count,"res":cursor}
    return dumps(res)

@app.route('/site/<string:hash>', methods = ['DELETE'])
def delete(hash):
    site_collection.delete_one({"_id":ObjectId(hash)})
    return 'true'

@app.route('/site/<string:id>', methods = ['POST'])
def update(id):
    updateInfo = request.get_json()
    try:
        res = dumps(site_collection.find_one_and_update({'_id':ObjectId(id)},updateInfo,return_document=ReturnDocument.AFTER))
    except Exception as e:
        res = str(e)
    return res


# Provide a method to create access tokens. The create_access_token()
# function is used to actually generate the token
@app.route('/login', methods=['POST'])
def login():
    username = request.json.get('username', None)
    password = request.json.get('password', None)
    expected = user_collection.find_one({"username":username})

    if expected is None or password != expected.password:
        return json.dumps({"msg": "Bad username or password"}), 401

    # Identity can be any data that is json serializable
    ret = {'access_token': create_access_token(identity=username)}
    return json.dumps(ret), 200

# Provide a method to create access tokens. The create_access_token()
# function is used to actually generate the token
@app.route('/owned/<string:id>/file', methods=['GET'])
@jwt_required

def checkOwnedFile(id):
    current_user = get_jwt_identity()
    site = site_collection.find({"_id":ObjectId(id)})
    owned = False
    if site is not None:
        try:
            res = r.get('http://'+get_tld(site.url)+'/'+current_user._id)
            if current_user._id in res.text:
                owned = True
        except:
            try:
                res = r.get('http://www.'+get_tld(site.url)+'/'+current_user._id)
                if current_user._id in res.text:
                    owned = True
                else:
                    owned = False
            except:
                owned = False
        if(owned):
            res = dumps(site_collection.find_one_and_update({'_id': ObjectId(id)}, {"$set":{owned:current_user._id}},
                                                            return_document=ReturnDocument.AFTER))
            return res
        else:
            return json.dumps(False)

@app.route('/owned/<string:id>/cname', methods=['GET'])
@jwt_required
def checkOwned(id):
    current_user = get_jwt_identity()
    site = site_collection.find({"_id":ObjectId(id)})
    url = 'http://'+current_user._id+get_tld(site.url)
    cname = dns.resolver.query(url, 'CNAME')
    owned = False
    for i in cname.response.answer:
        for j in i.items:
            if 'leyline.cc' in j.to_text():
                owned = True
                break
    if (owned):
        res = dumps(site_collection.find_one_and_update({'_id': ObjectId(id)}, {"$set": {owned: current_user._id}},
                                                        return_document=ReturnDocument.AFTER))
        return res
    else:
        return json.dumps(False)



# Provide a method to create access tokens. The create_access_token()
# function is used to actually generate the token
@app.route('/reg', methods=['POST'])
def reg():
    username = request.json.get('username', None)
    password = request.json.get('password', None)
    if checkNameExists(username):
        return False
    else:
        user_collection.insert({"username":username,"password":password})

@app.route('/reg/exists/<string:username>', methods=['GET'])
def checkNameExists(username):
    expected = user_collection.find_one({"username": username})
    return expected is not None


@app.route('/protected', methods=['GET'])
@jwt_required
def protected():
    # Access the identity of the current user with get_jwt_identity
    current_user = get_jwt_identity()
    return json.dumps({'hello_from': current_user}), 200


if __name__ == '__main__':
    app.run()
