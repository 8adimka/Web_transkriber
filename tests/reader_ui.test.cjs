// Dependency-free browser regression checks. Only synthetic REST/WS/media are used.
// Run: node --test tests/frontend_ui.test.cjs (Chrome/Chromium must be installed).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('node:http');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');

const root = path.resolve(__dirname, '..');
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const defaults = { microphone_enabled: false, tab_audio_enabled: true, original_language: 'EN', translation_language: 'RU', ui_language: 'en', theme: 'dark' };

class CDP {
    constructor(socket) {
        this.socket = socket;
        this.nextId = 0;
        this.pending = new Map();
        this.exceptions = [];
        socket.addEventListener('message', event => {
            const message = JSON.parse(event.data);
            if (message.method === 'Runtime.exceptionThrown') this.exceptions.push(message.params.exceptionDetails.exception?.description || message.params.exceptionDetails.text);
            if (!message.id) return;
            const pending = this.pending.get(message.id);
            if (!pending) return;
            clearTimeout(pending.timer);
            this.pending.delete(message.id);
            if (message.error) pending.reject(new Error(JSON.stringify(message.error)));
            else pending.resolve(message.result);
        });
    }
    send(method, params = {}) {
        return new Promise((resolve, reject) => {
            const id = ++this.nextId;
            const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
            this.pending.set(id, { resolve, reject, timer });
            this.socket.send(JSON.stringify({id,method,params}));
        });
    }
    async evaluate(expression) {
        const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
        if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
        return result.result.value;
    }
    async wait(expression, timeout = 7000) {
        const deadline = Date.now() + timeout;
        while (Date.now() < deadline) {
            if (await this.evaluate(expression)) return;
            await delay(35);
        }
        throw new Error('Condition not met: ' + expression);
    }
}

// The Reader uses real layout and selection; only account/document/translation IO is synthetic.
const readerMocks = `(() => {
    if (!localStorage.getItem('__reader_test_initialized')) {
        localStorage.clear();
        localStorage.setItem('__reader_test_initialized', 'yes');
        localStorage.setItem('access_token', 'synthetic-reader-access');
        localStorage.setItem('refresh_token', 'synthetic-reader-refresh');
        localStorage.setItem('user_info', JSON.stringify({id:42,email:'reader@example.test',full_name:'Test Reader'}));
    }
    Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{enumerateDevices:async()=>[]}});
})();`;
const longText = Array.from({length:48},(_,index) => `Paragraph ${index+1}. Alice reads beside the window. She finds a thoughtful sentence and follows it into another idea. The morning light moves slowly across the room, while the book waits for its next reader.`).join('\n\n');

async function harness() {
    let preferences = {...defaults};
    let nextId = 601;
    const documents = new Map([[501,{id:501,title:'Previously saved conversation',content:longText,source_lang:'EN',target_lang:'RU',position:0,page:1,progress_updated_at_ms:0,created_at:'2026-11-07T10:00:00Z'}]]);
    const creates = [];
    const imports = [];
    const translations = [];
    const progress = [];
    const readerRequests = [];
    const ids = new Map();
    const flags = {translateDelay:0,translateError:null,createDelay:0,createError:false,importError:null};
    const temp = await fs.mkdtemp(path.join(os.tmpdir(),'reader-browser-'));
    const json = (response,status,value) => { response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'}); response.end(JSON.stringify(value)); };
    const server = createServer(async (request,response) => {
        try {
            const url = new URL(request.url,'http://localhost');
            if (url.pathname.startsWith('/user/')) {
                if (request.method==='PUT') {
                    let source='';for await(const chunk of request) source+=chunk;
                    preferences={...preferences,...JSON.parse(source)};
                }
                json(response,200,{settings:preferences,updated:true});return;
            }
            if (url.pathname==='/transcriptions') {
                json(response,200,{transcriptions:[...documents.values()].reverse().map(doc=>({id:doc.id,filename:doc.title,content:doc.content.slice(0,300),created_at:doc.created_at,orig_language:doc.source_lang,translate_to:doc.target_lang,file_size:doc.content.length})),total:documents.size,skip:0,limit:10});return;
            }
            const prefix='/api/transcriber/reader';
            if (url.pathname.startsWith(prefix)) {
                readerRequests.push({method:request.method,path:url.pathname,authorization:request.headers.authorization});
                assert.equal(request.headers.authorization,'Bearer synthetic-reader-access');
                const relative=url.pathname.slice(prefix.length);
                const match=relative.match(/^\/documents\/(\d+)(\/progress)?$/);
                if (match) {
                    const doc=documents.get(Number(match[1]));
                    if (!doc) {json(response,404,{detail:{code:'not_found',message:'Synthetic missing document'}});return;}
                    if (request.method==='PATCH') {
                        let body='';for await(const chunk of request) body+=chunk;
                        const update=JSON.parse(body);
                        progress.push({id:doc.id,...update});
                        Object.assign(doc,update);
                    }
                    json(response,200,{...doc});return;
                }
                if (relative==='/documents' && request.method==='POST') {
                    let source='';for await(const chunk of request) source+=chunk;
                    const body=JSON.parse(source);creates.push(body);
                    if(!body.title.isWellFormed()){json(response,422,{detail:{code:'invalid_document',message:'Synthetic Unicode title validation'}});return;}
                    if (flags.createDelay) await delay(flags.createDelay);
                    if (flags.createError) {json(response,503,{detail:{code:'save_failed',message:'Synthetic save unavailable'}});return;}
                    let doc=documents.get(ids.get(body.client_id));
                    if (!doc) {
                        doc={id:nextId++,title:body.title,content:body.content,source_lang:body.source_lang,target_lang:body.target_lang,position:0,page:1,created_at:new Date().toISOString()};
                        ids.set(body.client_id,doc.id);documents.set(doc.id,doc);
                    }
                    json(response,200,{...doc});return;
                }
                if (relative==='/import' && request.method==='POST') {
                    const pieces=[];for await(const chunk of request) pieces.push(chunk);
                    const filename=decodeURIComponent(request.headers['x-file-name']||'');
                    imports.push({filename,body:Buffer.concat(pieces),source_lang:url.searchParams.get('source_lang'),target_lang:url.searchParams.get('target_lang')});
                    if(flags.importError){json(response,flags.importError.status,{detail:{code:flags.importError.code,message:'Synthetic unreadable document'}});return;}
                    const doc={id:nextId++,title:filename,content:`Imported ${filename}.\n\n${longText}`,source_lang:'EN',target_lang:'RU',position:0,page:1,created_at:new Date().toISOString()};
                    documents.set(doc.id,doc);json(response,200,{...doc});return;
                }
                if (relative==='/translate' && request.method==='POST') {
                    let source='';for await(const chunk of request) source+=chunk;
                    const body=JSON.parse(source);translations.push(body);
                    const failure=flags.translateError;
                    if (flags.translateDelay) await delay(flags.translateDelay);
                    if (failure) {json(response,failure.status,{detail:{code:failure.code,message:'Synthetic translation failure'}});return;}
                    json(response,200,{translated:'Translated: '+body.text,source_lang:body.source_lang,target_lang:body.target_lang});return;
                }
                json(response,404,{detail:{code:'not_found',message:'Unknown test route'}});return;
            }
            const filename=path.resolve(root,'frontend',url.pathname==='/'?'index.html':decodeURIComponent(url.pathname.slice(1)));
            if (!filename.startsWith(path.resolve(root,'frontend')+path.sep)) {response.writeHead(403).end();return;}
            const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'};
            response.writeHead(200,{'Content-Type':types[path.extname(filename)]||'application/octet-stream','Cache-Control':'no-store'});
            response.end(await fs.readFile(filename));
        } catch(error) {
            if (!response.headersSent) json(response,500,{detail:{code:'test_server_error',message:error.message}});
            else response.end();
        }
    });
    let chrome;
    let cdp;
    try {
        server.listen(0,'127.0.0.1');await once(server,'listening');
        const origin=`http://127.0.0.1:${server.address().port}`;
        chrome=spawn(process.env.CHROME_BIN||'/usr/bin/google-chrome-stable',['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--disable-background-networking',`--user-data-dir=${path.join(temp,'profile')}`,'--remote-debugging-port=0','about:blank'],{stdio:['ignore','ignore','pipe']});
        const address=await new Promise((resolve,reject)=>{
            let output='';const timer=setTimeout(()=>reject(new Error('Chrome did not start; set CHROME_BIN to an installed Chrome/Chromium binary')),15000);
            chrome.on('error',error=>{clearTimeout(timer);reject(error);});
            chrome.stderr.on('data',chunk=>{output+=chunk.toString();const match=output.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(timer);resolve(new URL(match[1]));}});
        });
        const targets=await(await fetch(`http://${address.host}/json/list`)).json();
        const socket=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
        await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true});});
        cdp=new CDP(socket);await cdp.send('Page.enable');await cdp.send('Runtime.enable');
        await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
        await cdp.send('Page.addScriptToEvaluateOnNewDocument',{source:readerMocks});
        return {cdp,documents,creates,imports,translations,progress,readerRequests,flags,
            async navigate(relative) {
                await cdp.send('Page.navigate',{url:origin+relative});
                await cdp.wait(`document.readyState==='complete' && !!window.UI && location.pathname===${JSON.stringify(new URL(relative,origin).pathname)}`);
            },
            async close() {
                cdp?.socket.close();
                if(chrome){chrome.kill('SIGTERM');await Promise.race([once(chrome,'exit'),delay(2000)]);}
                server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
                await fs.rm(temp,{recursive:true,force:true,maxRetries:5,retryDelay:100});
            }
        };
    } catch(error) {
        cdp?.socket.close();chrome?.kill('SIGTERM');server.closeAllConnections();server.close();
        await fs.rm(temp,{recursive:true,force:true,maxRetries:5,retryDelay:100});throw error;
    }
}

async function until(check,message,timeout=8000) {
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline){if(await check())return;await delay(30);}
    throw new Error(message);
}
async function paste(cdp,text) {
    await cdp.evaluate(`(() => {
        const input=document.querySelector('#readerInput');input.focus();
        const data=new DataTransfer();data.setData('text/plain',${JSON.stringify(text)});
        const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});
        input.dispatchEvent(event);
        if(!event.defaultPrevented){input.value=${JSON.stringify(text)};input.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertFromPaste',data:${JSON.stringify(text)}}));}
    })()`);
}
async function selection(cdp,start,end,within='#readerPage') {
    return cdp.evaluate(`(() => {
        const element=document.querySelector(${JSON.stringify(within)});
        const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);const nodes=[];
        while(walker.nextNode())nodes.push(walker.currentNode);
        const range=document.createRange();let position=0;let started=false;let ended=false;
        for(const node of nodes){const length=node.textContent.length;
            if(!started && ${start} < position+length){range.setStart(node,Math.max(0,${start}-position));started=true;}
            if(started && ${end} <= position+length){range.setEnd(node,Math.max(0,${end}-position));ended=true;break;}
            position+=length;
        }
        if(!started)throw new Error('Selection start exceeds rendered text');
        if(!ended){const node=nodes.at(-1);range.setEnd(node,node.textContent.length);}
        const selected=window.getSelection();selected.removeAllRanges();selected.addRange(range);
        const rect=range.getBoundingClientRect();
        element.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:rect.left+2,clientY:rect.top+2}));
        element.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,clientX:rect.left+2,clientY:rect.top+2}));
        return selected.toString().trim().replace(/\\s+/g,' ');
    })()`);
}
async function clickWord(cdp) {
    const point=await cdp.evaluate(`(() => {
        window.getSelection().removeAllRanges();
        const walker=document.createTreeWalker(document.querySelector('#readerPage'),NodeFilter.SHOW_TEXT);
        while(walker.nextNode()){
            const node=walker.currentNode;const match=node.textContent.match(/[\\p{L}\\p{M}]+/u);if(!match)continue;
            const range=document.createRange();range.setStart(node,match.index);range.setEnd(node,match.index+match[0].length);
            const rect=range.getClientRects()[0];if(rect?.width)return{x:rect.left+rect.width/2,y:rect.top+rect.height/2};
        }
        throw new Error('No word found on this page');
    })()`);
    await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...point});
    await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...point});
}
async function outside(cdp) {
    await cdp.evaluate(`document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));document.body.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));document.body.dispatchEvent(new MouseEvent('click',{bubbles:true}));`);
}

// A single isolated browser is shared by sequential subtests, just like a reading session.
test('Reader import, pagination, translation, persistence and responsive layout',{timeout:120000},async t=>{
    const h=await harness();const {cdp}=h;let pastedId;let resumePage;let resumeText;
    t.beforeEach(() => { h.flags.translateDelay=0; h.flags.translateError=null; });
    try {
        await t.test('paste opens a saved book once and every page fits without losing text',async()=>{
            await h.navigate('/');await cdp.wait(`!!window.Reader && !!document.querySelector('#tabReader')`);
            assert.equal(await cdp.evaluate(`document.querySelector('[data-ui-language]')===null`),true,'interface language belongs in Profile');
            await cdp.evaluate(`document.querySelector('#tabReader').click()`);
            await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            await paste(cdp,longText);
            await cdp.wait(`!document.querySelector('#readerBook').hidden && !Reader.state.paginating && Number(document.querySelector('#readerPageTotal').textContent)>2`,20000);
            await until(()=>h.creates.length===1,'paste did not create exactly one document');
            await until(()=>h.documents.size===2,'reader did not save pasted text');
            pastedId=[...h.documents.keys()].find(id=>id!==501);
            assert.equal(h.creates[0].content,longText);
            const pages=await cdp.evaluate(`Number(document.querySelector('#readerPageTotal').textContent)`);
            assert.ok(pages>2&&pages<200,'reasonable synthetic book page count');
            await cdp.evaluate(`document.querySelector('#readerFirst').click()`);
            const content=[];
            for(let page=1;page<=pages;page++){
                await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===${page}`);
                const view=await cdp.evaluate(`(() => {const e=document.querySelector('#readerPage');return{text:e.textContent,height:e.clientHeight,scroll:e.scrollHeight};})()`);
                assert.ok(view.height>0,'page must have positive reading height');
                assert.ok(view.scroll<=view.height+1,`page ${page} overflows: ${view.scroll}>${view.height}`);
                content.push(view.text);
                if(page<pages)await cdp.evaluate(`document.querySelector('#readerNext').click()`);
            }
            assert.equal(content.join('').replace(/\s+/g,' ').trim(),longText.replace(/\s+/g,' ').trim(),'pagination must preserve the complete text');
            assert.equal(await cdp.evaluate(`document.querySelector('#readerNext').disabled`),true);
            await cdp.evaluate(`document.querySelector('#readerFirst').click()`);await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===1`);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPrevious').disabled`),true);
            await cdp.evaluate(`(() => {const page=document.querySelector('#readerPageNumber');page.value='3';page.dispatchEvent(new Event('change',{bubbles:true}));page.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()`);
            await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===3`);
            await cdp.evaluate(`document.querySelector('#readerSideNext').click()`);await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===4`);
            await cdp.evaluate(`document.querySelector('#readerSidePrevious').click()`);await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===3`);
            await cdp.evaluate(`document.querySelector('#readerLast').click()`);await cdp.wait(`Number(document.querySelector('#readerPageNumber').value)===${pages}`);
            await cdp.evaluate(`document.querySelector('#readerFirst').click()`);
        });
        await t.test('a word and real multi-sentence selection use the Workspace language pair',async()=>{
            await cdp.evaluate(`document.querySelector('#sourceLang').value='ES';document.querySelector('#sourceLang').dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#targetLang').value='EN';document.querySelector('#targetLang').dispatchEvent(new Event('change',{bubbles:true}));`);
            const before=h.translations.length;await clickWord(cdp);
            await until(()=>h.translations.length===before+1,'word click did not request translation');
            await cdp.wait(`!document.querySelector('#readerPopover').hidden && document.querySelector('#readerPopoverText').textContent.startsWith('Translated: ')`);
            assert.equal(h.translations.at(-1).source_lang,'ES');assert.equal(h.translations.at(-1).target_lang,'EN');
            assert.match(h.translations.at(-1).text,/^[\p{L}\p{M}'’-]+$/u);
            await outside(cdp);assert.equal(await cdp.evaluate(`document.querySelector('#readerPopover').hidden`),true);
            const phrase=await selection(cdp,0,125);
            assert.ok(phrase.includes('.'),'selection should include sentences');
            await until(()=>h.translations.at(-1)?.text===phrase,'selected phrase was not translated in full');
            await cdp.wait(`document.querySelector('#readerPopoverText').textContent===${JSON.stringify('Translated: ')}+${JSON.stringify(phrase)}`);
            const calls=h.translations.length;
            const selectedTranslation=await selection(cdp,0,30,'#readerPopoverText');
            assert.ok(selectedTranslation.length>0);
            await delay(150);
            assert.equal(h.translations.length,calls,'selecting inside the popup must not translate again');
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPopover').hidden`),false);
            assert.notEqual(await cdp.evaluate(`getComputedStyle(document.querySelector('#readerPopoverText')).userSelect`),'none');
        });
        await t.test('dismissed stale responses stay hidden, errors permit retry',async()=>{
            await outside(cdp);h.flags.translateDelay=350;
            const before=h.translations.length;await selection(cdp,135,185);
            await until(()=>h.translations.length===before+1,'delayed translation did not start');
            await outside(cdp);await delay(400);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPopover').hidden`),true,'a stale response must not reopen the popup');
            h.flags.translateDelay=0;h.flags.translateError={status:503,code:'translation_unavailable'};
            const phrase=await selection(cdp,190,230);
            await until(()=>h.translations.at(-1)?.text===phrase,'error translation did not start');
            await cdp.wait(`!document.querySelector('#readerPopover').hidden && !!document.querySelector('#readerPopoverStatus').textContent && document.querySelector('#readerPopoverStatus').textContent!==UI.t('reader.translating')`);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPopoverText').textContent.startsWith('Translated: ')`),false);
            h.flags.translateError=null;await outside(cdp);
            const count=h.translations.length;await selection(cdp,190,230);
            await until(()=>h.translations.length===count+1,'failed translations must be retriable');
            await cdp.wait(`document.querySelector('#readerPopoverText').textContent.startsWith('Translated: ')`);
            await outside(cdp);
        });
        await t.test('reading position survives Saved texts navigation and font reflow',async()=>{
            await cdp.evaluate(`(() => {const page=document.querySelector('#readerPageNumber');page.value='3';page.dispatchEvent(new Event('change',{bubbles:true}));})()`);
            await until(()=>h.progress.some(item=>item.id===pastedId&&item.page===3),'page navigation did not persist progress');
            resumePage=await cdp.evaluate(`Number(document.querySelector('#readerPageNumber').value)`);
            resumeText=await cdp.evaluate(`document.querySelector('#readerPage').textContent.slice(0,45)`);
            await h.navigate('/transcriptions.html');await cdp.wait(`!!document.querySelector('a[href="index.html?reader=${pastedId}"]')`);
            await cdp.evaluate(`document.querySelector('a[href="index.html?reader=${pastedId}"]').click()`);
            await cdp.wait(`!!window.Reader && !document.querySelector('#readerBook').hidden && !Reader.state.paginating && Number(document.querySelector('#readerPageNumber').value)===${resumePage}`,15000);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPage').textContent.slice(0,45)`),resumeText);
            const anchor=await cdp.evaluate(`document.querySelector('#readerPage').textContent.trim().slice(0,30)`);
            const size=await cdp.evaluate(`getComputedStyle(document.querySelector('#readerPage')).fontSize`);
            await cdp.evaluate(`document.querySelector('#readerFontIncrease').click()`);
            await cdp.wait(`getComputedStyle(document.querySelector('#readerPage')).fontSize!==${JSON.stringify(size)}`);
            await cdp.wait(`document.querySelector('#readerPage').textContent.includes(${JSON.stringify(anchor)})`);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPage').scrollHeight<=document.querySelector('#readerPage').clientHeight+1`),true);
        });
        await t.test('dragged TXT and FB2 documents are saved, existing audio texts also open',async()=>{
            for(const extension of ['txt','fb2']){
                await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
                await cdp.evaluate(`(() => {const data=new DataTransfer();data.items.add(new File(['Synthetic ${extension} content'],'sample.${extension}',{type:'application/octet-stream'}));document.querySelector('#readerInput').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));})()`);
                await until(()=>h.imports.at(-1)?.filename===`sample.${extension}`,'drop did not send file content');
                await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerTitle').textContent==='sample.${extension}'`,15000);
            }
            assert.equal(h.imports.length,2);assert.ok(h.imports.every(file=>file.body.length>0));
            await h.navigate('/index.html?reader=501');await cdp.wait(`!document.querySelector('#readerBook').hidden && !Reader.state.paginating && document.querySelector('#readerPage').textContent.length>50 && document.querySelector('#readerTitle').textContent==='Previously saved conversation'`);
            assert.ok(await cdp.evaluate(`document.querySelector('#readerPage').textContent.length>50`));
        });
        await t.test('mobile focus mode fits the viewport and keeps translation controls outside text',async()=>{
            await cdp.send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
            await delay(150);
            await cdp.evaluate(`document.querySelector('#readerFocus').click()`);await cdp.wait(`document.body.classList.contains('reader-focus')`);
            await cdp.wait(`document.querySelector('#readerPage').clientHeight>200`);
            assert.equal(await cdp.evaluate(`document.documentElement.scrollWidth<=innerWidth`),true);
            assert.equal(await cdp.evaluate(`document.querySelector('.reader-pagination').getBoundingClientRect().bottom<=innerHeight+2`),true,'reader controls fit vertically');
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPage').scrollHeight<=document.querySelector('#readerPage').clientHeight+1`),true);
            assert.equal(await cdp.evaluate(`(() => {const text=document.querySelector('#readerPage').getBoundingClientRect();return document.querySelector('#readerSidePrevious').getBoundingClientRect().right<=text.left+1 && document.querySelector('#readerSideNext').getBoundingClientRect().left>=text.right-1;})()`),true);
            await cdp.evaluate(`UI.setTheme('light')`);assert.equal(await cdp.evaluate(`document.documentElement.dataset.theme`),'light');
            await delay(120);await cdp.wait(`!Reader.state.paginating && document.querySelector('#readerPageTotal').textContent!=='…'`);
            await selection(cdp,0,70);await cdp.wait(`!document.querySelector('#readerPopover').hidden && document.querySelector('#readerPopoverText').textContent.startsWith('Translated: ')`);
            const bounds=await cdp.evaluate(`(() => {const r=document.querySelector('#readerPopover').getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};})()`);
            assert.ok(bounds.left>=0&&bounds.right<=390&&bounds.top>=0&&bounds.bottom<=844,'translation popup fits mobile viewport');
            if(process.env.READER_SCREENSHOTS==='1'){const screenshot=await cdp.send('Page.captureScreenshot',{format:'png'});await fs.writeFile('/tmp/web-transcriber-reader-mobile.png',Buffer.from(screenshot.data,'base64'));}
            await outside(cdp);
            await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
            await cdp.evaluate(`UI.setTheme('dark');if(document.body.classList.contains('reader-focus'))document.querySelector('#readerFocus').click()`);
            await delay(150);await cdp.wait(`!Reader.state.paginating && document.querySelector('#readerPageTotal').textContent!=='…'`);
            await selection(cdp,0,70);await cdp.wait(`!document.querySelector('#readerPopover').hidden && document.querySelector('#readerPopoverText').textContent.startsWith('Translated: ')`);
            if(process.env.READER_SCREENSHOTS==='1'){const desktop=await cdp.send('Page.captureScreenshot',{format:'png'});await fs.writeFile('/tmp/web-transcriber-reader-dark.png',Buffer.from(desktop.data,'base64'));}
            await outside(cdp);
        });
        await t.test('a failed autosave keeps the text and resumes its idempotent draft after reload',async()=>{
            await cdp.send('Emulation.setDeviceMetricsOverride',{width:1440,height:1050,deviceScaleFactor:1,mobile:false});
            await h.navigate('/index.html?reader=501');
            await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerPage').textContent.length>50`);
            await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            h.flags.createError=true;const before=h.creates.length;const count=h.documents.size;
            const draft='A synthetic offline reading draft. This text must survive a failed save and a full reload.';
            await paste(cdp,draft);
            await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerPage').textContent.includes('synthetic offline reading draft') && document.querySelector('#readerSaveStatus').classList.contains('error')`);
            assert.equal(h.documents.size,count);
            assert.equal(h.creates.length,before+1);
            const clientId=h.creates.at(-1).client_id;
            h.flags.createError=false;
            await h.navigate('/?mode=reader');
            await until(()=>[...h.documents.values()].some(doc=>doc.content===draft),'the persisted draft was not retried after reload');
            await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerPage').textContent.includes('synthetic offline reading draft')`);
            assert.equal(h.creates.at(-1).client_id,clientId,'restored drafts reuse their idempotency key');
            assert.equal([...h.documents.values()].filter(doc=>doc.content===draft).length,1);
        });
        await t.test('typed text opens with Read text and markup stays harmless selectable text',async()=>{
            await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            const typed='A typed reading note. <img src=x onerror="window.__readerXss=true"> Unicode: Привет 😊.';
            await cdp.evaluate(`document.querySelector('#readerInput').value=${JSON.stringify(typed)};document.querySelector('#readerRead').click()`);
            await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerPage').textContent.includes('A typed reading note.')`);
            assert.equal(await cdp.evaluate(`!window.__readerXss && !document.querySelector('#readerPage img')`),true);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerPage').textContent`),typed);
            await cdp.wait(`!!Reader.state.documentId`);
            assert.equal([...h.documents.values()].filter(doc=>doc.content===typed).length,1);
        });
        await t.test('an unreadable PDF is not retried after reload and does not block the next valid import',async()=>{
            await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            const before=h.imports.length;h.flags.importError={status:422,code:'no_text_layer'};
            await cdp.evaluate(`(() => {const data=new DataTransfer();data.items.add(new File(['%PDF synthetic scan'],'unreadable.pdf',{type:'application/pdf'}));document.querySelector('#readerInput').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));})()`);
            await cdp.wait(`document.querySelector('#readerImportStatus').classList.contains('error') && !document.querySelector('#readerChooseFile').disabled`);
            assert.equal(h.imports.length,before+1);
            assert.equal(await cdp.evaluate(`document.querySelector('#readerBook').hidden`),true);
            await h.navigate('/?mode=reader');await cdp.wait(`!!window.Reader && !document.querySelector('#readerImport').hidden`);
            await delay(150);assert.equal(h.imports.length,before+1,'permanent import errors must not remain queued');
            h.flags.importError=null;
            await cdp.evaluate(`(() => {const data=new DataTransfer();data.items.add(new File(['A valid text after a bad scan.'],'after-scan.txt',{type:'text/plain'}));document.querySelector('#readerInput').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));})()`);
            await cdp.wait(`!document.querySelector('#readerBook').hidden && document.querySelector('#readerTitle').textContent==='after-scan.txt' && document.querySelector('#readerPage').textContent.length>20`);
            assert.equal(h.imports.length,before+2);
        });
        await t.test('a title boundary preserves an emoji instead of creating an unpaired surrogate',async()=>{
            await cdp.wait(`!!Reader.state.documentId && !document.querySelector('#readerNew').disabled`);
            await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            const content='A'.repeat(119)+'😀tail';const before=h.creates.length;
            await paste(cdp,content);
            await cdp.wait(`!!Reader.state.documentId && !document.querySelector('#readerBook').hidden`);
            assert.equal(h.creates.length,before+1);
            const title=h.creates.at(-1).title;
            assert.equal(title.isWellFormed(),true,'generated titles must remain valid Unicode');
            assert.equal(title,'A'.repeat(119)+'😀');
            assert.equal([...h.documents.values()].filter(doc=>doc.content===content).length,1,'the document must save successfully rather than return 422');
        });
        await t.test('a pending account-A draft is never sent using account-B credentials',async()=>{
            await cdp.wait(`!document.querySelector('#readerNew').disabled`);
            await cdp.evaluate(`document.querySelector('#readerNew').click()`);await cdp.wait(`!document.querySelector('#readerImport').hidden`);
            const text='Synthetic account-A private reading draft. It must remain with account A.';
            const before=h.readerRequests.length;
            try{
                // importText suspends at its IndexedDB write before making the POST.
                // Change identities in the same JS turn while that asynchronous write is pending.
                await cdp.evaluate(`Reader.importText(${JSON.stringify(text)});localStorage.setItem('user_info',JSON.stringify({id:99,email:'other-reader@example.test',full_name:'Other Reader'}));localStorage.setItem('access_token','synthetic-account-B-access');localStorage.setItem('refresh_token','synthetic-account-B-refresh');`);
                await cdp.wait(`document.querySelector('#readerBook').hidden && document.querySelector('#readerPage').textContent==='' && document.querySelector('#readerInput').value==='' && document.querySelector('#readerImportStatus').textContent===UI.t('reader.accountChanged')`);
                const records=await cdp.evaluate(`new Promise((resolve,reject)=>{const opening=indexedDB.open('web-transcriber-reader',1);opening.onerror=()=>reject(opening.error);opening.onsuccess=()=>{const db=opening.result;const request=db.transaction('pending').objectStore('pending').getAll();request.onsuccess=()=>{resolve(request.result.map(record=>({owner:record.owner,content:record.draft?.content})));db.close();};request.onerror=()=>reject(request.error);};})`);
                assert.ok(records.some(record=>record.owner==='42'&&record.content===text),'the pending draft stays in account A storage');
                assert.ok(!records.some(record=>record.owner==='99'&&record.content===text),'account B must not receive the draft');
                assert.equal(h.readerRequests.slice(before).filter(request=>request.method==='POST'&&request.path.endsWith('/documents')).length,0,'no document POST may start after the identity switch');
                assert.equal(h.readerRequests.some(request=>request.authorization==='Bearer synthetic-account-B-access'),false);
                assert.equal([...h.documents.values()].some(doc=>doc.content===text),false);
            }finally{
                await cdp.evaluate(`localStorage.setItem('user_info',JSON.stringify({id:42,email:'reader@example.test',full_name:'Test Reader'}));localStorage.setItem('access_token','synthetic-reader-access');localStorage.setItem('refresh_token','synthetic-reader-refresh');`);
                await h.navigate('/?mode=reader');
            }
            await until(()=>[...h.documents.values()].some(doc=>doc.content===text),'account A could not recover its retained draft');
            await cdp.wait(`!!Reader.state.documentId && document.querySelector('#readerPage').textContent.includes('account-A private reading draft')`);
        });
        assert.deepEqual(cdp.exceptions,[],'Reader must not raise uncaught browser exceptions');
    } finally {await h.close();}
});
