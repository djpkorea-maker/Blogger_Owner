/** R3 guarded write Bridge. Deploy separately. Writes OFF by default.
 * Script properties: R3_BLOG_ID, R3_BRIDGE_SECRET.
 */
function doPost(e) {
  try {
    var props = PropertiesService.getScriptProperties();
    var secret = props.getProperty('R3_BRIDGE_SECRET');
    var blogId = props.getProperty('R3_BLOG_ID');
    if (!secret || !blogId) throw new Error('configuration_missing');
    var request = JSON.parse(e.postData.contents);
    if (String(request.secret || '') !== secret) throw new Error('unauthorized');
    var p = request.payload || {};
    var base = 'https://www.googleapis.com/blogger/v3/blogs/' + encodeURIComponent(blogId) + '/posts';
    if (request.action === 'list_metadata') {
      var state = String(p.status || '').toUpperCase();
      if (['LIVE','SCHEDULED','DRAFT'].indexOf(state) < 0) throw new Error('invalid_status');
      var url = base + '?view=ADMIN&fetchBodies=false&fetchImages=false&maxResults=100&status=' + state.toLowerCase();
      url += '&fields=' + encodeURIComponent('nextPageToken,items(id,status,updated,title,url,published,labels)');
      if (p.pageToken) url += '&pageToken=' + encodeURIComponent(String(p.pageToken));
      var data = R3_API_GET_(url);
      var items = (data.items || []).map(function(post) {
        post.status = String(post.status || '').toUpperCase();
        if (post.status !== state || !post.id || !post.updated) throw new Error('metadata_invalid');
        return post;
      });
      return R3_JSON_({ok:true,blogId:blogId,status:state,items:items,nextPageToken:String(data.nextPageToken || '')});
    }
    if (request.action === 'get_post') {
      var id = String(p.postId || '');
      if (!/^\d+$/.test(id)) throw new Error('invalid_post_id');
      var post = R3_API_GET_(base + '/' + id + '?view=ADMIN');
      post.status = String(post.status || '').toUpperCase();
      if (['LIVE','SCHEDULED','DRAFT'].indexOf(post.status)<0) throw new Error('admin_status_missing');
      return R3_JSON_({ok:true,blogId:blogId,post:post});
    }
    if (request.action==='request_status') return R3_JSON_(R3_REQUEST_STATUS_(p,blogId));
    if (['apply_update','rollback','upload_image','create_draft','publish_pass'].indexOf(request.action)>=0) {
      if (props.getProperty('R3_ENABLE_WRITES')!=='true') throw new Error('writes_disabled');
      return R3_JSON_(R3_WRITE_(request.action,p,blogId,base));
    }
    throw new Error('unknown_action');
  } catch (err) {
    return R3_JSON_({ok:false,error:String(err.message || 'bridge_failed')});
  }
}
function R3_API_GET_(url) {
  var res = UrlFetchApp.fetch(url, {method:'get',muteHttpExceptions:true,headers:{Authorization:'Bearer '+ScriptApp.getOAuthToken()}});
  var code = res.getResponseCode();
  if (code < 200 || code >= 300) throw new Error('blogger_http_' + code);
  return JSON.parse(res.getContentText());
}
function R3_REQUEST_STATUS_(p,blogId) {
  var id=String(p.requestId||'');
  if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error('request_id_required');
  // Read only: never create an audit folder or replay the original operation.
  var folderId=PropertiesService.getScriptProperties().getProperty('R3_AUDIT_FOLDER_ID');
  if (!folderId) return {ok:true,blogId:blogId,status:'NOT_FOUND'};
  var files=DriveApp.getFolderById(folderId).getFilesByName('request_'+id+'.json');
  if (!files.hasNext()) return {ok:true,blogId:blogId,status:'NOT_FOUND'};
  var saved=JSON.parse(files.next().getBlob().getDataAsString('UTF-8'));
  return {ok:true,blogId:blogId,status:saved.status,action:saved.action,result:saved.status==='DONE'?saved.result:null};
}
function R3_JSON_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
function R3_HASH_(post) {
  // Same sorted-key JSON and UTF-8 SHA256 as Python post_hash.
  var value={content:String(post.content||''),labels:post.labels||[],status:String(post.status||'').toUpperCase(),title:String(post.title||'')};
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,JSON.stringify(value),Utilities.Charset.UTF_8)
    .map(function(b){return ('0'+((b+256)%256).toString(16)).slice(-2);}).join('');
}
function R3_FOLDER_(key,name) {
  var props=PropertiesService.getScriptProperties();var id=props.getProperty(key);
  if (id) return DriveApp.getFolderById(id);
  var folder=DriveApp.createFolder(name);props.setProperty(key,folder.getId());return folder;
}
function R3_API_PATCH_(url,body) {
  var res=UrlFetchApp.fetch(url,{method:'patch',contentType:'application/json',payload:JSON.stringify(body),muteHttpExceptions:true,headers:{Authorization:'Bearer '+ScriptApp.getOAuthToken()}});
  if (res.getResponseCode()<200 || res.getResponseCode()>=300) throw new Error('patch_http_'+res.getResponseCode());
}
function R3_WRITE_(action,p,blogId,base) {
  var lock=LockService.getScriptLock();if (!lock.tryLock(5000)) throw new Error('bridge_busy');
  try {
    var requestId=String(p.requestId||'');
    if (!/^[a-f0-9-]{36}$/.test(requestId)) throw new Error('request_id_required');
    var signature=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,action+'\n'+JSON.stringify(p),Utilities.Charset.UTF_8).map(function(b){return ('0'+((b+256)%256).toString(16)).slice(-2);}).join('');
    var folder=R3_FOLDER_('R3_AUDIT_FOLDER_ID','Blogger_R3_Backups');
    var existing=folder.getFilesByName('request_'+requestId+'.json');
    if (existing.hasNext()) {
      var prior=JSON.parse(existing.next().getBlob().getDataAsString('UTF-8'));
      if (prior.signature!==signature) throw new Error('request_payload_mismatch');
      if (prior.status==='DONE') return prior.result;
      throw new Error('request_outcome_unknown_no_retry');
    }
    // Journal BEFORE any side effect. Interrupted requests must be reconciled manually.
    var journal=folder.createFile('request_'+requestId+'.json',JSON.stringify({status:'RUNNING',action:action,requestId:requestId,signature:signature}),MimeType.PLAIN_TEXT);
    var result;
    if (action==='create_draft') {
      if (p.confirm!=='CREATE_PASS_DRAFT' || !String(p.title||'').trim() || String(p.content||'').length<1500 || !Array.isArray(p.labels)) throw new Error('draft_invalid');
      var created=R3_API_POST_(base+'?isDraft=true',{title:p.title,content:p.content,labels:p.labels});
      var stored=R3_API_GET_(base+'/'+encodeURIComponent(created.id)+'?view=ADMIN');
      if (R3_HASH_(stored)!==R3_HASH_({title:p.title,content:p.content,labels:p.labels,status:'DRAFT'})) throw new Error('draft_verification_failed');
      result={ok:true,blogId:blogId,postId:String(stored.id),status:'DRAFT',verified:true};
    } else if (action==='publish_pass') {
      if (p.confirm!=='PUBLISH_PASS_POST' || ['LIVE','SCHEDULED'].indexOf(p.mode)<0 || !/^\d+$/.test(String(p.postId||''))) throw new Error('publish_invalid');
      var publishBase=base+'/'+encodeURIComponent(p.postId);
      var original=R3_API_GET_(publishBase+'?view=ADMIN');
      if (String(original.status||'').toUpperCase()!=='DRAFT' || R3_HASH_(original)!==p.expectedHash || original.updated!==p.expectedUpdated) throw new Error('publish_conflict');
      var publishUrl=publishBase+'/publish';
      if (p.mode==='SCHEDULED') {
        var when=new Date(p.publishDate);
        if (!isFinite(when.getTime()) || when.getTime()<=Date.now()+60000) throw new Error('schedule_must_be_future');
        publishUrl+='?publishDate='+encodeURIComponent(when.toISOString());
      }
      folder.createFile('post_'+String(p.postId)+'_'+requestId+'.json',JSON.stringify({blogId:blogId,post:original,action:action}),MimeType.PLAIN_TEXT);
      var publishLatest=R3_API_GET_(publishBase+'?view=ADMIN');
      if (R3_HASH_(publishLatest)!==p.expectedHash || publishLatest.updated!==p.expectedUpdated) throw new Error('publish_conflict_after_backup');
      R3_API_POST_(publishUrl,null);
      var published=R3_API_GET_(publishBase+'?view=ADMIN');
      if (String(published.status||'').toUpperCase()!==p.mode) throw new Error('publish_status_mismatch');
      if (p.mode==='SCHEDULED' && new Date(published.published).getTime()!==new Date(p.publishDate).getTime()) throw new Error('publish_time_mismatch');
      result={ok:true,blogId:blogId,postId:String(published.id),status:p.mode,verified:true};
    } else if (action==='upload_image') {
      if (p.confirm!=='UPLOAD_ONE_IMAGE') throw new Error('confirmation_mismatch');
      if (['image/jpeg','image/png','image/webp'].indexOf(p.mimeType)<0) throw new Error('image_mime');
      var bytes=Utilities.base64Decode(String(p.base64||''));
      if (!bytes.length || bytes.length>2*1024*1024) throw new Error('image_size');
      var images=R3_FOLDER_('R3_IMAGE_FOLDER_ID','Blogger_R3_Images');
      var image=images.createFile(Utilities.newBlob(bytes,p.mimeType,String(p.fileName||'image').replace(/[^\w.가-힣-]/g,'_')));
      try {image.setSharing(DriveApp.Access.ANYONE_WITH_LINK,DriveApp.Permission.VIEW);} catch (err) {image.setTrashed(true);throw new Error('image_sharing_failed');}
      var byteHash=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,bytes).map(function(b){return ('0'+((b+256)%256).toString(16)).slice(-2);}).join('');
      result={ok:true,blogId:blogId,fileId:image.getId(),byte_hash:byteHash,publicImageUrl:'https://lh3.googleusercontent.com/d/'+image.getId()+'=w1024'};
    } else {
      var pid=String(p.postId||'');if (!/^\d+$/.test(pid)) throw new Error('post_id_invalid');
      var url=base+'/'+pid;var before=R3_API_GET_(url+'?view=ADMIN');
      if (R3_HASH_(before)!==p.expectedHash || String(before.updated||'')!==String(p.expectedUpdated||'')) throw new Error('live_conflict');
      var body;
      if (action==='apply_update') {
        if (p.confirm!=='APPLY_ONE_POST' || String(before.url||'')!==String(p.expectedUrl||'')) throw new Error('confirmation_or_url_mismatch');
        if (!String(p.title||'').trim() || String(p.content||'').length<200 || /<h1\b/i.test(p.content)) throw new Error('content_invalid');
        if (!Array.isArray(p.labels)) throw new Error('labels_invalid');
        body={title:p.title,content:p.content,labels:p.labels};
      } else {
        if (p.confirm!=='ROLLBACK_ONE_POST') throw new Error('confirmation_mismatch');
        var file=DriveApp.getFileById(String(p.backupFileId||''));
        var parents=file.getParents();var owned=false;while(parents.hasNext()) {if(parents.next().getId()===folder.getId())owned=true;}
        if (!owned) throw new Error('backup_folder_mismatch');
        var backup=JSON.parse(file.getBlob().getDataAsString('UTF-8'));
        if (backup.blogId!==blogId || String(backup.post.id)!==pid) throw new Error('backup_identity_mismatch');
        body={title:backup.post.title||'',content:backup.post.content||'',labels:backup.post.labels||[]};
      }
      var saved=folder.createFile('post_'+pid+'_'+requestId+'.json',JSON.stringify({blogId:blogId,post:before,action:action,requestId:requestId}),MimeType.PLAIN_TEXT);
      // Recheck after backup too: catches edits during backup creation.
      var latest=R3_API_GET_(url+'?view=ADMIN');
      if (R3_HASH_(latest)!==p.expectedHash || String(latest.updated)!==String(p.expectedUpdated) || String(latest.url||'')!==String(before.url||'')) throw new Error('live_conflict_after_backup');
      R3_API_PATCH_(url,body);
      var after=R3_API_GET_(url+'?view=ADMIN');
      var desired={title:body.title,content:body.content,labels:body.labels,status:before.status};
      if (R3_HASH_(after)!==R3_HASH_(desired) || after.url!==before.url) throw new Error('verification_failed_manual_reconcile');
      result={ok:true,blogId:blogId,postId:pid,backupFileId:saved.getId(),verified:true,afterHash:R3_HASH_(after),updated:after.updated};
    }
    journal.setContent(JSON.stringify({status:'DONE',action:action,requestId:requestId,signature:signature,result:result}));
    return result;
  } finally {lock.releaseLock();}
}

function R3_API_POST_(url,body) {
  var options={method:'post',muteHttpExceptions:true,headers:{Authorization:'Bearer '+ScriptApp.getOAuthToken()}};
  if (body!==null) {options.contentType='application/json';options.payload=JSON.stringify(body);}
  var response=UrlFetchApp.fetch(url,options);
  if (response.getResponseCode()<200 || response.getResponseCode()>=300) throw new Error('post_http_'+response.getResponseCode());
  return JSON.parse(response.getContentText()||'{}');
}
