/** R3 standalone READ ONLY Bridge. Deploy separately from R2; no write actions.
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
    throw new Error('read_only_unknown_action');
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
function R3_JSON_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
