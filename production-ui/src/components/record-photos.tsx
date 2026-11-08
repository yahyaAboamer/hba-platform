"use client";
import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ImagePlus, Images, Search, Upload, X } from 'lucide-react';
import { Panel } from '@/components/ui';
type Photo={id:string;name:string;url:string;mimeType:string;size:number;createdAt:string};
type LibraryPhoto=Photo & {source:string;sourceKind:'order'|'sample'};
type Mode='upload'|'library';

export function RecordPhotos({recordId,recordName,canUpload,kind='order',onSaved}:{recordId:string;recordName:string;canUpload:boolean;kind?:'order'|'sample';onSaved?:()=>Promise<void>}) {
  const endpoint = `/api/production/${kind}-photos`;
  const [photos,setPhotos]=useState<Photo[]>([]);
  const [files,setFiles]=useState<File[]>([]);
  const [loading,setLoading]=useState(true);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [status,setStatus]=useState('');
  const [mode,setMode]=useState<Mode>('upload');
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
  async function attach(ids:string[]) {
    setBusy(true);setError('');setStatus('');
    try {
      const response=await fetch(`${endpoint}/attach`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({[kind]:recordId,photoIds:ids})});
      const result=await response.json() as {photos?:Photo[];error?:string};
      if(!response.ok) throw new Error(result.error || 'Could not add those photos');
      const added=result.photos ?? [];
      if(added.length) setPhotos(current=>[...added,...current]);
      const skipped=ids.length-added.length;
      setStatus(added.length
        ? `${added.length} ${added.length===1 ? 'photo' : 'photos'} added to ${recordName}${skipped ? ` · ${skipped} already here` : ''}`
        : `${ids.length===1 ? 'That photo is' : 'Those photos are'} already on this ${kind}`);
      setMode('upload');
      if(added.length && onSaved) void onSaved();
    } catch(error) {setError(error instanceof Error ? error.message : 'Could not add those photos');}
    finally {setBusy(false);}
  }
  return <Panel title={kind === 'sample' ? 'Sample photos' : 'Order photos'} description={`${recordName} · Product, fabric and sample photos`}>
    <div className="order-photos">
      {canUpload ? <>
        <div className="segmented photo-mode" role="tablist" aria-label="How to add photos">
          <button type="button" role="tab" aria-selected={mode==='upload'} className={mode==='upload' ? 'active' : ''} disabled={busy} onClick={()=>setMode('upload')}><Upload size={15}/> Upload new</button>
          <button type="button" role="tab" aria-selected={mode==='library'} className={mode==='library' ? 'active' : ''} disabled={busy} onClick={()=>{setMode('library');setError('');setStatus('');}}><Images size={15}/> Choose existing</button>
        </div>
        {mode==='upload'
          ? <form className="photo-upload-form" onSubmit={upload}><label className="photo-file-label"><ImagePlus size={20}/><span>Choose photos<small>JPG, PNG, WebP or GIF · up to 20 MB each</small></span><input ref={input} type="file" multiple accept="image/jpeg,image/png,image/webp,image/gif" aria-label={kind === 'sample' ? 'Choose sample photos' : 'Choose production order photos'} disabled={busy} onChange={event=>{setFiles(Array.from(event.target.files || []));setError('');setStatus('');}}/></label>{files.length>0 && <div className="photo-selection"><span>{files.length} selected: {files.map(file=>file.name).join(', ')}</span><button type="submit" className="button primary" disabled={busy}><Upload size={16}/>{busy ? 'Uploading…' : 'Upload photos'}</button></div>}</form>
          : <PhotoLibrary kind={kind} current={photos} busy={busy} onCancel={()=>setMode('upload')} onAdd={ids=>void attach(ids)}/>}
      </> : <p>Sign in with an owner or production account to add photos.</p>}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert" className="danger-text">{error} <button className="text-button" disabled={busy} onClick={()=>{setLoading(true);setError('');void load().catch(error=>setError(error instanceof Error ? error.message : 'Could not load photos')).finally(()=>setLoading(false));}}>Reload photos</button></p>}
      {mode==='upload' && (loading ? <p>Loading photos…</p> : photos.length ? <div className="order-photo-grid">{photos.map(photo=><figure key={photo.id}><a href={photo.url} target="_blank" rel="noopener noreferrer"><img src={photo.url} alt={photo.name} loading="lazy"/></a><figcaption>{photo.name}</figcaption></figure>)}</div> : <div className="photo-empty"><ImagePlus size={30}/><p>No photos added to this {kind} yet.</p></div>)}
    </div>
  </Panel>;
}

/** Every photo already on the server, to reuse without uploading again. */
function PhotoLibrary({kind,current,busy,onCancel,onAdd}:{kind:'order'|'sample';current:Photo[];busy:boolean;onCancel:()=>void;onAdd:(ids:string[])=>void}) {
  const [photos,setPhotos]=useState<LibraryPhoto[]>([]);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [search,setSearch]=useState('');
  const [chosen,setChosen]=useState<string[]>([]);
  const here=useMemo(()=>new Set(current.map(photo=>photo.id)),[current]);
  useEffect(()=>{
    const controller=new AbortController();
    fetch('/api/production/photo-library',{cache:'no-store',signal:controller.signal})
      .then(async response=>{const result=await response.json() as {photos?:LibraryPhoto[];error?:string};if(!response.ok) throw new Error(result.error || 'Could not load the photo library');setPhotos(result.photos ?? []);})
      .catch(error=>{if(!controller.signal.aborted) setError(error instanceof Error ? error.message : 'Could not load the photo library');})
      .finally(()=>{if(!controller.signal.aborted) setLoading(false);});
    return ()=>controller.abort();
  },[]);
  const needle=search.trim().toLowerCase();
  const shown=photos.filter(photo=>!needle || `${photo.name} ${photo.source}`.toLowerCase().includes(needle));
  function toggle(id:string) {setChosen(list=>list.includes(id) ? list.filter(item=>item!==id) : [...list,id]);}
  return <div className="photo-library">
    <div className="photo-library-bar">
      <div className="search-field"><Search size={16}/><input value={search} onChange={event=>setSearch(event.target.value)} placeholder="Search by photo, order or sample name" aria-label="Search the photo library"/>{search && <button type="button" onClick={()=>setSearch('')} aria-label="Clear search"><X size={14}/></button>}</div>
      <span>{loading ? '' : `${shown.length} of ${photos.length} ${photos.length===1 ? 'photo' : 'photos'}`}</span>
    </div>
    {error && <p role="alert" className="danger-text">{error}</p>}
    {loading ? <p>Loading the photo library…</p> : !photos.length ? <div className="photo-empty"><Images size={30}/><p>No photos on the server yet. Upload one first.</p></div> : !shown.length ? <p className="muted-text">No photos match “{search}”.</p> :
      <div className="order-photo-grid photo-library-grid" role="group" aria-label="Photos to choose from">{shown.map(photo=>{
        const already=here.has(photo.id);
        const picked=chosen.includes(photo.id);
        return <button type="button" key={photo.id} className={`photo-choice ${picked ? 'picked' : ''}`} aria-pressed={picked} disabled={already || busy} onClick={()=>toggle(photo.id)} title={already ? `Already on this ${kind}` : photo.name}>
          <img src={photo.url} alt="" loading="lazy"/>
          <span className="photo-check" aria-hidden="true">{picked && <Check size={14}/>}</span>
          <span className="photo-choice-text"><strong>{photo.name}</strong><small>{already ? `Already on this ${kind}` : `${photo.sourceKind==='order' ? 'Order' : 'Sample'} · ${photo.source}`}</small></span>
        </button>;
      })}</div>}
    <div className="photo-library-actions"><button type="button" className="button subtle" disabled={busy} onClick={onCancel}>Cancel</button><button type="button" className="button primary" disabled={busy || !chosen.length} onClick={()=>onAdd(chosen)}><Check size={16}/>{busy ? 'Adding…' : chosen.length ? `Add ${chosen.length} ${chosen.length===1 ? 'photo' : 'photos'}` : 'Choose photos'}</button></div>
  </div>;
}
