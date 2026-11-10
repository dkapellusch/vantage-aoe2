// Small DOM model for identity/focus tests; HTML parsing stays a browser check.
export class Element {
  constructor(name='DIV', attrs={}, children=[], doc={activeElement:null}) {
    this.nodeType=1;this.nodeName=name.toUpperCase();this.namespaceURI='html';
    this.ownerDocument=doc;this.attrs=new Map(Object.entries(attrs));this.childNodes=[];this.scrollTop=0;
    for(const child of children)this.insertBefore(child,null);
  }
  get tagName(){return this.nodeName;}
  get id(){return this.getAttribute('id')||'';}
  get attributes(){return [...this.attrs].map(([name,value])=>({name,value}));}
  get dataset(){return {panelDetail:this.getAttribute('data-panel-detail')};}
  get open(){return this.hasAttribute('open');}
  set open(value){if(value)this.setAttribute('open','');else this.removeAttribute('open');}
  get firstChild(){return this.childNodes[0]||null;}
  get nextSibling(){const list=this.parentNode?.childNodes||[];return list[list.indexOf(this)+1]||null;}
  get details(){return this.querySelectorAll('details[data-panel-detail]');}
  get summary(){return this.querySelector('summary');}
  getAttribute(name){return this.attrs.has(name)?this.attrs.get(name):null;}
  hasAttribute(name){return this.attrs.has(name);}
  setAttribute(name,value){this.attrs.set(name,String(value));}
  removeAttribute(name){this.attrs.delete(name);}
  contains(node){return this===node||this.childNodes.some(child=>child.contains?.(node));}
  insertBefore(node,before){
    if(node===before)return node;
    if(node.parentNode)node.parentNode.removeChild(node);
    this.childNodes.splice(before?this.childNodes.indexOf(before):this.childNodes.length,0,node);
    node.parentNode=this;return node;
  }
  removeChild(node){
    if(node.contains?.(this.ownerDocument.activeElement))this.ownerDocument.activeElement=null;
    this.childNodes.splice(this.childNodes.indexOf(node),1);node.parentNode=null;return node;
  }
  replaceChildren(...nodes){for(const node of [...this.childNodes])this.removeChild(node);for(const node of nodes)this.insertBefore(node,null);this.scrollTop=0;}
  cloneNode(deep){return new Element(this.nodeName,Object.fromEntries(this.attrs),deep?this.childNodes.map(node=>node.cloneNode(true)):[],this.ownerDocument);}
  matches(selector){return selector.startsWith('details')?this.nodeName==='DETAILS'&&this.hasAttribute('data-panel-detail'):this.nodeName===selector.toUpperCase();}
  querySelectorAll(selector){return this.childNodes.flatMap(node=>[...(node.matches?.(selector)?[node]:[]),...(node.querySelectorAll?.(selector)||[])]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  closest(selector){for(let node=this;node;node=node.parentNode)if(node.matches(selector))return node;return null;}
  focus(){this.ownerDocument.activeElement=this;}
  set innerHTML(value){
    // The selection tests encode their fixture rather than emulate an HTML parser.
    const data=JSON.parse(value),doc=this.ownerDocument;
    this.replaceChildren(new Text(String(data.revision)),...data.keys.map(key=>
      new Element('details',{'data-panel-detail':key},[new Element('summary',{},[],doc)],doc)));
  }
}
export class Text {
  constructor(value){this.nodeType=3;this.nodeName='#text';this.nodeValue=value;}
  get nextSibling(){const list=this.parentNode?.childNodes||[];return list[list.indexOf(this)+1]||null;}
  cloneNode(){return new Text(this.nodeValue);}
}
