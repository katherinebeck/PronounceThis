import React from "react";

// The "Pronounce This." wordmark (coral stress mark + period) as an image.
export default function Logo({ className = "h-5", alt = "Pronounce This.", ...rest }) {
  return <img src="/landing/logo@600.png" alt={alt} className={"inline-block w-auto " + className} draggable={false} {...rest} />;
}
