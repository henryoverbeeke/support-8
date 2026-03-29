import React from "react";
import { Composition } from "remotion";
import { ProductPreview } from "./ProductPreview";

export const RemotionRoot = () => {
  return (
    <>
      <Composition
        id="ProductPreview"
        component={ProductPreview}
        durationInFrames={600}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
