"use client";
import { useEffect, useRef, useState } from 'react';
import { ImagePlus, Upload } from 'lucide-react';
import { Panel } from '@/components/ui';
type Photo={id:string;name:string;url:string;mimeType:string;size:number;createdAt:string};
export function RecordPhotos({recordId,recordName,canUpload,kind='order',onSaved}:{recordId:string;recordName:string;canUpload:boolean;kind?:'order'|'sample';onSaved?:()=>Promise<void>}) {
  const endpoint = `/api/production/${kind}-photos`;
  const [photos,setPhotos]=useState<Photo[]>([]);
  const [files,setFiles]=useState<File[]>([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [status,setStatus]=useState('');
  const input=useRef<HTMLInputElement>(null);
  const sequence=useRef(0);
  async function load(signal?:AbortSignal) {
    const requestId=++sequence.current;
    const response=await fetch(`${endpoint}?${kind}=${encodeURIComponent(recordId)}`,{cache:'no-store',signal});
    const result=await response.json() as {photos:Photo[];error?:string};
    if(!response.ok) throw new Error(result.error || 'Could not load photos');
    if(requestId===sequence.current) setPhotos(result.photos);
  }
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError('');
    void load(controller.signal).catch(error=>{if(!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Could not load photos');}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  // Each order mounts its own gallery; the parent keys this component by order ID.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[recordId]);
  async function upload(event:React.FormEvent<HTMLFormElement>) {
    event.preventDefault();setBusy(true);setError('');setStatus('');
    const pending=[...files];let saved=0;
    try {
      for(let index=0;index<pending.length;index++) {
        const file=pending[index];
        if(file.size>20*1024*1024) throw new Error(`${file.name}: photos must be 20 MB or smaller`);
        setStatus(`Uploading ${index+1} of ${pending.length}…`);
        const form=new FormData();form.set(kind,recordId);form.set('file',file);
        const response=await fetch(endpoint,{method:'POST',body:form});
        const result=await response.json() as {photo?:Photo;error?:string};
        if(!response.ok) throw new Error(result.error || `Could not upload ${file.name}`);
        if(result.photo) setPhotos(current=>[result.photo!,...current]);
        saved++;setFiles(pending.slice(index+1));
      }
      if(input.current) input.current.value='';
      setStatus(`${saved} ${saved===1 ? 'photo' : 'photos'} saved to ${recordName}`);
    } catch(error) {setStatus(saved ? `${saved} ${saved===1 ? 'photo' : 'photos'} saved` : '');setError(error instanceof Error ? error.message : 'Could not upload photos');}
    finally {setBusy(false);if(saved && onSaved) void onSaved();}
  }
  return <Panel title={kind === 'sample' ? 'Sample photos' : 'Order photos'} description={`${recordName} · Product, fabric and sample photos`}>
    <div className="order-photos">
      {canUpload ? <form className="photo-upload-form" onSubmit={upload}><label className="photo-file-label"><ImagePlus size={20}/><span>Choose photos<small>JPG, PNG, WebP or GIF · up to 20 MB each</small></span><input ref={input} type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif" aria-label={kind === 'sample' ? 'Choose sample photos' : 'Choose production order photos'} disabled={busy} onChange={event=>{setFiles(Array.from(event.target.files || []));setError('');setStatus('');}}/></label>{files.length>0 && <div className="photo-selection"><span>{files.length} selected: {files.map(file=>file.name).join(', ')}</span><button type="submit" className="button primary" disabled={busy}><Upload size={16}/>{busy ? 'Uploading…' : 'Upload photos'}</button></div>}</form> : <p>Sign in with an owner or production account to add photos.</p>}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert" className="danger-text">{error} <button className="text-button" disabled={busy} onClick={()=>{setLoading(true);setError('');void load().catch(error=>setError(error instanceof Error ? error.message : 'Could not load photos')).finally(()=>setLoading(false));}}>Reload photos</button></p>}
      {loading ? <p>Loading photos…</p> : photos.length ? <div className="order-photo-grid">{photos.map(photo=><figure key={photo.id}><a href={photo.url} target="_blank" rel="noopener noreferrer"><img src={photo.url} alt={photo.name} loading="lazy"/></a><figcaption>{photo.name}</figcaption></figure>)}</div> : <div className="photo-empty"><ImagePlus size={30}/><p>No photos added to this {kind} yet.</p></div>}
    </div>
  </Panel>;
}
