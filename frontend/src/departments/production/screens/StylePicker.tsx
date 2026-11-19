import { useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import type { ChoiceProduct } from "./types";

/** One line of the list: a product, the order's own style that is no longer listed, or "a new style". */
export type StyleOption = { id: string; title: string; status?: ChoiceProduct["status"]; image_url?: string | null };

/** The products whose title holds what was typed, anywhere in it, in any case. */
export function filterProducts<T extends { title: string }>(products: readonly T[], query: string): T[] {
  const wanted = query.trim().toLocaleLowerCase();
  if (!wanted) return [...products];
  return products.filter((product) => product.title.toLocaleLowerCase().includes(wanted));
}

/**
 * A Shopify image at thumbnail size. The product's own image is the full photo (often 4000 px), which
 * makes a long list crawl; Shopify's CDN sends a small copy when asked for a width. Other addresses
 * are left as they are.
 */
export function thumbUrl(url: string): string {
  try {
    const address = new URL(url);
    if (address.hostname !== "cdn.shopify.com") return url;
    address.searchParams.set("width", "96");
    return address.toString();
  } catch {
    return url;
  }
}

function Thumb({ url }: { url: string | null | undefined }) {
  return url ? (
    <img className="prod-style__thumb" src={thumbUrl(url)} alt="" loading="lazy" />
  ) : (
    <span className="prod-style__thumb prod-style__thumb--none" aria-hidden="true" />
  );
}

/**
 * The style box of New order and Edit the order: type part of a product's name and the list narrows as
 * you type, each product with its picture and a "Draft" tag on a draft. An accessible combobox (the
 * ARIA 1.2 pattern): arrows move, Enter picks, Escape closes, a click picks. "A new style, not on Shopify
 * yet" is always the last line.
 */
export function StylePicker({
  label,
  products,
  value,
  extra,
  newStyle,
  onPick,
}: {
  label: string;
  products: readonly ChoiceProduct[];
  /** The chosen id: a product's, `newStyle.id`, the order's own (`extra`), or `""`. */
  value: string;
  /** The order's own style when it is not in the list any more, kept so it can stay chosen. */
  extra: StyleOption | null;
  newStyle: StyleOption;
  onPick: (id: string) => void;
}) {
  const id = useId();
  const listId = `${id}-list`;
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const options = useMemo<StyleOption[]>(() => {
    const found: StyleOption[] = filterProducts(products, query);
    if (extra && filterProducts([extra], query).length) found.push(extra);
    found.push(newStyle);
    return found;
  }, [products, query, extra, newStyle]);

  const chosen: StyleOption | null =
    products.find((product) => product.id === value) ?? (extra && extra.id === value ? extra : null) ?? (value === newStyle.id ? newStyle : null);
  const optionId = (index: number) => `${id}-option-${index}`;
  const at = Math.min(active, options.length - 1);

  function show() {
    if (open) return;
    setQuery("");
    // Start on the chosen one, so Enter keeps it.
    const all: StyleOption[] = [...products, ...(extra ? [extra] : []), newStyle];
    setActive(Math.max(0, all.findIndex((option) => option.id === value)));
    setOpen(true);
  }

  function pick(option: StyleOption) {
    onPick(option.id);
    setOpen(false);
    setQuery("");
    input.current?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!open) show();
        else setActive(Math.min(at + 1, options.length - 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        if (!open) show();
        else setActive(Math.max(at - 1, 0));
        break;
      case "Home":
        if (open) {
          event.preventDefault();
          setActive(0);
        }
        break;
      case "End":
        if (open) {
          event.preventDefault();
          setActive(options.length - 1);
        }
        break;
      case "Enter":
        if (open) {
          event.preventDefault();
          pick(options[at]);
        }
        break;
      case "Escape":
        if (open) {
          // Closes the list only, not the panel the form sits in.
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          setQuery("");
        }
        break;
    }
  }

  return (
    <div className="prod-field prod-style">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <div className="prod-style__box">
        {!open && chosen && chosen.id !== newStyle.id && <Thumb url={chosen.image_url} />}
        <input
          ref={input}
          id={id}
          className="input"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && options.length ? optionId(at) : undefined}
          autoComplete="off"
          placeholder={open ? (chosen ? chosen.title : "Type part of the name") : "Choose a style…"}
          value={open ? query : (chosen?.title ?? "")}
          onClick={show}
          onBlur={() => {
            setOpen(false);
            setQuery("");
          }}
          onChange={(event) => {
            if (!open) setOpen(true);
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      <ul
        id={listId}
        role="listbox"
        aria-label="Products"
        className="prod-style__list"
        hidden={!open}
        // Keep focus in the box while a line is pressed, so the press picks rather than closes.
        onMouseDown={(event) => event.preventDefault()}
      >
        {open &&
          options.map((option, index) => {
            const isNew = option === newStyle;
            return (
              <li
                key={`${option.id}-${index}`}
                id={optionId(index)}
                role="option"
                aria-selected={index === at}
                className={`prod-style__option${index === at ? " prod-style__option--active" : ""}${isNew ? " prod-style__option--new" : ""}`}
                onClick={() => pick(option)}
                onMouseMove={() => index !== at && setActive(index)}
              >
                {!isNew && <Thumb url={option.image_url} />}
                <span className="prod-style__title">{option.title}</span>
                {option.status === "draft" && <span className="prod-pill prod-style__draft">Draft</span>}
                {option.id === value && <span className="prod-sr"> (chosen)</span>}
              </li>
            );
          })}
      </ul>
      {open && options.length === 1 && <span className="field__hint" role="status">No product matches “{query.trim()}”.</span>}
    </div>
  );
}
