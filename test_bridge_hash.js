// Executes guarded Bridge hash in mocked Apps Script context, no network.
const fs=require('fs'),vm=require('vm'),crypto=require('crypto'),assert=require('assert');
const context={Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},computeDigest:(algo,value)=>Array.from(crypto.createHash('sha256').update(value,'utf8').digest())}};
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/bridge/Blogger_Guarded_Bridge_R3.gs','utf8'),context);
const post={title:'전기 점검 😀',content:'<p>줄바꿈\n"확인"</p>',labels:['가전','전기'],status:'LIVE'};
const canonical=JSON.stringify({content:post.content,labels:post.labels,status:post.status,title:post.title});
assert.equal(context.R3_HASH_(post),crypto.createHash('sha256').update(canonical,'utf8').digest('hex'));
console.log('Bridge UTF-8 hash test passed');
context.ScriptApp={getOAuthToken:()=> 'mock-token'};
let patches=0;const files=new Map();
context.PropertiesService={getScriptProperties:()=>({getProperty:()=> 'folder',setProperty:()=>{}})};
const folder={getFilesByName:(name)=>({hasNext:()=>files.has(name),next:()=>({getBlob:()=>({getDataAsString:()=>files.get(name)})})}),createFile:(name,content)=>{files.set(name,content);return {setContent:v=>files.set(name,v),getId:()=>name};}};
context.DriveApp={getFolderById:()=>folder};context.MimeType={PLAIN_TEXT:'text/plain'};
context.LockService={getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})};
context.UrlFetchApp={fetch:(url,opt)=>{if(opt.method==='patch')patches++;return {getResponseCode:()=>200,getContentText:()=>JSON.stringify({...post,id:'1',url:'https://example.com/p',updated:'v2'})};}};
const request={requestId:'11111111-1111-1111-1111-111111111111',postId:'1',expectedHash:'stale',expectedUpdated:'v1',confirm:'APPLY_ONE_POST'};
assert.throws(()=>context.R3_WRITE_('apply_update',request,'blog','https://example.com/posts'),/live_conflict/);
assert.equal(patches,0);
assert.throws(()=>context.R3_WRITE_('apply_update',request,'blog','https://example.com/posts'),/request_outcome_unknown_no_retry/);
assert.equal(patches,0);
console.log('Bridge stale conflict and no replay tests passed');

const beforeFiles=files.size;
const unknown=context.R3_REQUEST_STATUS_({requestId:request.requestId},'blog');
assert.equal(unknown.status,'RUNNING');assert.equal(unknown.result,null);
assert.equal(files.size,beforeFiles);assert.equal(patches,0);
const doneId='22222222-2222-2222-2222-222222222222';
files.set('request_'+doneId+'.json',JSON.stringify({status:'DONE',action:'create_draft',result:{blogId:'blog',postId:'12',status:'DRAFT',verified:true}}));
const done=context.R3_REQUEST_STATUS_({requestId:doneId},'blog');
assert.equal(done.action,'create_draft');assert.equal(done.result.postId,'12');
assert.equal(patches,0);
assert.equal(context.R3_REQUEST_STATUS_({requestId:'33333333-3333-3333-3333-333333333333'},'blog').status,'NOT_FOUND');
console.log('Bridge read-only request reconciliation tests passed');

let reads=0;
context.UrlFetchApp.fetch=(url,opt)=>{
  if(opt.method==='patch')patches++;
  reads++;
  return {getResponseCode:()=>200,getContentText:()=>JSON.stringify({...post,id:'1',updated:'v2',url:reads===1?'https://example.com/p':'https://example.com/changed'})};
};
const urlRace={requestId:'44444444-4444-4444-4444-444444444444',postId:'1',expectedHash:context.R3_HASH_(post),expectedUpdated:'v2',expectedUrl:'https://example.com/p',confirm:'APPLY_ONE_POST',title:'새 제목',content:'<p>'+('새 본문 '.repeat(100))+'</p>',labels:['전기']};
assert.throws(()=>context.R3_WRITE_('apply_update',urlRace,'blog','https://example.com/posts'),/live_conflict_after_backup/);
assert.equal(reads,2);assert.equal(patches,0);
console.log('Bridge URL change during backup blocks PATCH test passed');

// Dev82 recovery relies on journal-before-file and same-ID replay protection.
let uploads=0;
const imageId='55555555-5555-4555-8555-555555555555';
const settings={R3_BLOG_ID:'blog',R3_BRIDGE_SECRET:'mock-secret',R3_ENABLE_WRITES:'true',R3_AUDIT_FOLDER_ID:'folder',R3_IMAGE_FOLDER_ID:'images'};
context.PropertiesService={getScriptProperties:()=>({getProperty:key=>settings[key],setProperty:(key,value)=>{settings[key]=value;}})};
context.Utilities.computeDigest=(algo,value)=>Array.from(crypto.createHash('sha256').update(Array.isArray(value)?Buffer.from(value):value,'utf8').digest());
context.Utilities.base64Decode=value=>Array.from(Buffer.from(value,'base64'));
context.Utilities.newBlob=(bytes,mime,name)=>({bytes,mime,name});
const imageFolder={createFile:blob=>{
  assert.equal(JSON.parse(files.get('request_'+imageId+'.json')).status,'RUNNING');
  uploads++;return {getId:()=> 'uploaded-image',setSharing:()=>{},setTrashed:()=>{}};
}};
context.DriveApp={getFolderById:id=>id==='images'?imageFolder:folder,Access:{ANYONE_WITH_LINK:'public'},Permission:{VIEW:'view'}};
context.ContentService={MimeType:{JSON:'json'},createTextOutput:text=>({setMimeType:()=>JSON.parse(text)})};
const countBefore=files.size;
const missing=context.R3_REQUEST_STATUS_({requestId:imageId},'blog');
assert.equal(missing.ok,true);assert.equal(missing.status,'NOT_FOUND');assert.equal(missing.blogId,'blog');
assert.equal(files.size,countBefore);assert.equal(uploads,0);
const uploadRequest={secret:'mock-secret',action:'upload_image',payload:{requestId:imageId,confirm:'UPLOAD_ONE_IMAGE',base64:Buffer.from('mock-image').toString('base64'),mimeType:'image/png',fileName:'scene.png'}};
const first=context.doPost({postData:{contents:JSON.stringify(uploadRequest)}});
assert.equal(first.ok,true);assert.equal(uploads,1);
const second=context.doPost({postData:{contents:JSON.stringify(uploadRequest)}});
assert.deepEqual(second,first);assert.equal(uploads,1);assert.equal(patches,0);
assert.equal(context.R3_REQUEST_STATUS_({requestId:imageId},'blog').status,'DONE');
settings.R3_ENABLE_WRITES='false';
assert.equal(context.doPost({postData:{contents:JSON.stringify(uploadRequest)}}).error,'writes_disabled');
assert.equal(uploads,1);
console.log('Bridge NOT_FOUND recovery, journal-before-upload and same-ID no-duplicate tests passed');
