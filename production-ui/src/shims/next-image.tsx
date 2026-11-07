/** `next/image` as Production used it: unoptimised, so a plain <img>. */
import type { ImgHTMLAttributes } from "react";

type Props = ImgHTMLAttributes<HTMLImageElement> & { unoptimized?: boolean };

export default function Image({ unoptimized: _unoptimized, alt, ...rest }: Props) {
  return <img alt={alt} {...rest} />;
}
