"use client";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal, Trash2, X } from 'lucide-react';

export type RowMenuItem={label:string;icon?:ReactNode;onSelect:()=>void;danger?:boolean;disabled?:boolean};

/** The ⋯ button on a row or card. The list is drawn at the top of the page
 * and placed against the window, so no table or panel can clip or trap it. */
export function RowMenu({label,items,className=''}:{label:string;items:RowMenuItem[];className?:string}) {
  const [open,setOpen]=useState(false);
  const [place,setPlace]=useState<{top:number;left:number}|null>(null);
  const button=useRef<HTMLButtonElement>(null);
  const list=useRef<HTMLDivElement>(null);
  const focused=useRef(false);
  /** Puts the list against its button; false when the button is out of view. */
  function position():boolean {
    if(!button.current) return false;
    const box=button.current.getBoundingClientRect();
    if(box.bottom<0 || box.top>window.innerHeight || box.right<0 || box.left>window.innerWidth) return false;
    const width=list.current?.offsetWidth ?? 180;
    const height=list.current?.offsetHeight ?? 0;
    const below=box.bottom+6+height<=window.innerHeight;
    setPlace({top:below ? box.bottom+6 : Math.max(8,box.top-6-height),left:Math.max(8,Math.min(box.right-width,window.innerWidth-width-8))});
    return true;
  }
  useLayoutEffect(()=>{
    focused.current=false;
    if(open) position();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[open]);
  useEffect(()=>{
    if(!open) return;
    function away(event:Event) {if(!list.current?.contains(event.target as Node) && !button.current?.contains(event.target as Node)) setOpen(false);}
    function key(event:KeyboardEvent) {if(event.key==='Escape'){setOpen(false);button.current?.focus();}}
    // The list follows its button as the page or the table scrolls, and
    // closes once the button has scrolled out of sight.
    function follow() {if(!position()) setOpen(false);}
    document.addEventListener('pointerdown',away);document.addEventListener('keydown',key);
    window.addEventListener('scroll',follow,true);window.addEventListener('resize',follow);
    return ()=>{document.removeEventListener('pointerdown',away);document.removeEventListener('keydown',key);window.removeEventListener('scroll',follow,true);window.removeEventListener('resize',follow);};
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[open]);
  useEffect(()=>{
    // Once placed (and visible), the first choice takes the keyboard.
    if(open && place && !focused.current) {
      focused.current=true;
      list.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({preventScroll:true});
    }
  },[open,place]);
  function move(event:React.KeyboardEvent<HTMLDivElement>) {
    if(event.key!=='ArrowDown' && event.key!=='ArrowUp') return;
    event.preventDefault();
    const buttons=Array.from(list.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
    const at=buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[(at+(event.key==='ArrowDown' ? 1 : buttons.length-1))%buttons.length]?.focus({preventScroll:true});
  }
  return <span className={`row-menu ${className}`} onClick={event=>event.stopPropagation()}>
    <button ref={button} type="button" className="row-menu-trigger" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={()=>{setPlace(null);setOpen(value=>!value);}}><MoreHorizontal size={17}/></button>
    {open && createPortal(<div ref={list} role="menu" aria-label={label} className="row-menu-list" style={place ? {top:place.top,left:place.left} : {visibility:'hidden',top:0,left:0}} onKeyDown={move}>
      {items.map(item=><button key={item.label} type="button" role="menuitem" className={item.danger ? 'danger' : ''} disabled={item.disabled} onClick={()=>{setOpen(false);item.onSelect();}}>{item.icon}{item.label}</button>)}
    </div>,document.body)}
  </span>;
}

/** "Are you sure?" before something is removed for everyone. */
export function ConfirmDelete({title,detail,busy,error,confirmLabel='Delete',onCancel,onConfirm}:{title:string;detail:ReactNode;busy:boolean;error?:string;confirmLabel?:string;onCancel:()=>void;onConfirm:()=>void}) {
  useEffect(()=>{
    function key(event:KeyboardEvent) {if(event.key==='Escape' && !busy) onCancel();}
    document.addEventListener('keydown',key);
    return ()=>document.removeEventListener('keydown',key);
  },[busy,onCancel]);
  return <div className="modal-backdrop" onClick={()=>{if(!busy) onCancel();}}>
    <section className="modal confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-detail" onClick={event=>event.stopPropagation()}>
      <header><div className="confirm-heading"><span className="confirm-icon"><Trash2 size={18}/></span><div><h2 id="confirm-title">{title}</h2></div></div><button className="icon-button" onClick={onCancel} disabled={busy} aria-label="Close"><X size={18}/></button></header>
      <div className="modal-form"><p id="confirm-detail" className="confirm-detail">{detail}</p>{error && <p role="alert" className="danger-text">{error}</p>}
        <footer><button className="button subtle" type="button" autoFocus disabled={busy} onClick={onCancel}>Cancel</button><button className="button danger" type="button" disabled={busy} onClick={onConfirm}><Trash2 size={15}/> {busy ? 'Deleting…' : confirmLabel}</button></footer>
      </div>
    </section>
  </div>;
}
