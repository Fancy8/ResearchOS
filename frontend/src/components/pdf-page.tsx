"use client";
import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentLoadingTask,
  PDFDocumentProxy,
  PDFPageProxy,
  RenderTask,
  TextLayer as PdfTextLayer,
  PageViewport,
} from "pdfjs-dist";
import { highlightExactText, type HighlightRect } from "@/lib/pdf-anchor";
import type {
  EvidenceOrigin,
  SelectionRect,
  Evidence,
} from "@/lib/evidence-draft";
import { ErrorBox } from "./common";

export type FileAddress = {
  url: string;
  paper_file_id: string;
  version_no: number;
  is_current: boolean;
  page_count: number;
  has_text_layer: boolean;
};
export type RenderedPage = EvidenceOrigin & { scale: number };

export function PdfPage({
  paperId,
  file,
  pageNumber,
  scale,
  source,
  onReady,
  onHighlightStatus,
  onSelection,
}: {
  paperId: string;
  file: FileAddress;
  pageNumber: number;
  scale: number;
  source?: Evidence;
  onReady: (value: RenderedPage | undefined) => void;
  onHighlightStatus: (value: string) => void;
  onSelection: (
    origin: EvidenceOrigin,
    text: string,
    rects: SelectionRect[],
  ) => void;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy>();
  const [error, setError] = useState<unknown>();
  const [reload, setReload] = useState(0);
  const [rendering, setRendering] = useState(true);
  const [highlights, setHighlights] = useState<HighlightRect[]>([]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const ready = useRef<{
    page: PDFPageProxy;
    viewport: PageViewport;
    pageNumber: number;
    scale: number;
  } | null>(null);
  useEffect(() => {
    let active = true;
    let loading: PDFDocumentLoadingTask | undefined;
    setPdf(undefined);
    setError(undefined);
    setRendering(true);
    ready.current = null;
    onReady(undefined);
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        if (!active) return;
        pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        loading = pdfjs.getDocument({
          url: file.url,
          disableAutoFetch: true,
          maxImageSize: 16_000_000,
        });
        const document = await loading.promise;
        if (active) setPdf(document);
      } catch (reason) {
        if (active) {
          setError(reason);
          setRendering(false);
        }
      }
    })();
    return () => {
      active = false;
      ready.current = null;
      void loading?.destroy();
    };
  }, [file.url, reload, onReady]);
  useEffect(() => {
    if (!pdf) return;
    let active = true;
    let render: RenderTask | undefined;
    let textTask: PdfTextLayer | undefined;
    ready.current = null;
    onReady(undefined);
    setRendering(true);
    setError(undefined);
    setHighlights([]);
    layer.current?.replaceChildren();
    if (canvas.current) {
      canvas.current.width = 0;
      canvas.current.height = 0;
    }
    onHighlightStatus("正在校验显示位置");
    void (async () => {
      try {
        const page = await pdf.getPage(pageNumber);
        if (!active || !canvas.current || !layer.current) return;
        const viewport = page.getViewport({ scale });
        const ratio = window.devicePixelRatio || 1;
        const target = canvas.current;
        target.width = viewport.width * ratio;
        target.height = viewport.height * ratio;
        target.style.width = `${viewport.width}px`;
        target.style.height = `${viewport.height}px`;
        layer.current.style.width = `${viewport.width}px`;
        layer.current.style.height = `${viewport.height}px`;
        layer.current.style.setProperty("--scale-factor", String(scale));
        layer.current.style.setProperty(
          "--total-scale-factor",
          String(scale * page.userUnit),
        );
        render = page.render({
          canvas: target,
          canvasContext: target.getContext("2d")!,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        });
        await render.promise;
        if (!active) return;
        const pdfjs = await import("pdfjs-dist");
        if (!active || !layer.current) return;
        const content = await page.getTextContent();
        if (!active || !layer.current) return;
        textTask = new pdfjs.TextLayer({
          textContentSource: content,
          container: layer.current,
          viewport,
        });
        await textTask.render();
        if (!active) return;
        if (
          source &&
          source.paper_file_id === file.paper_file_id &&
          source.page_start === pageNumber
        ) {
          const rects =
            source.anchor_status === "located"
              ? highlightExactText(layer.current, source.quote_text)
              : null;
          setHighlights(rects ?? []);
          onHighlightStatus(
            rects
              ? "已重新校验并高亮原文"
              : "仅定位到页码，当前显示无法精确高亮",
          );
        } else if (source) onHighlightStatus("请打开证据的原始文件版本与页码");
        ready.current = { page, viewport, pageNumber, scale };
        onReady({
          paperId,
          fileId: file.paper_file_id,
          version: file.version_no,
          page: pageNumber,
          hasText: file.has_text_layer,
          scale,
        });
      } catch (reason) {
        if (active) setError(reason);
      } finally {
        if (active) setRendering(false);
      }
    })();
    return () => {
      active = false;
      ready.current = null;
      render?.cancel();
      textTask?.cancel();
    };
  }, [
    pdf,
    paperId,
    file.paper_file_id,
    file.version_no,
    file.has_text_layer,
    pageNumber,
    scale,
    source,
    onReady,
    onHighlightStatus,
  ]);
  function captureSelection() {
    const context = ready.current;
    const selection = window.getSelection();
    if (
      !context ||
      context.pageNumber !== pageNumber ||
      context.scale !== scale ||
      !selection?.rangeCount ||
      !selection.toString().trim() ||
      !layer.current?.contains(selection.anchorNode) ||
      !layer.current.contains(selection.focusNode) ||
      !canvas.current
    )
      return;
    const bounds = canvas.current.getBoundingClientRect();
    const [x1, y1, x2, y2] = context.page.view;
    const rects = Array.from(selection.getRangeAt(0).getClientRects())
      .filter((box) => box.width && box.height)
      .map((box) => {
        const corners = [
          [box.left, box.top],
          [box.right, box.top],
          [box.left, box.bottom],
          [box.right, box.bottom],
        ].map(([x, y]) =>
          context.viewport.convertToPdfPoint(x - bounds.left, y - bounds.top),
        );
        const minX = Math.max(x1, Math.min(...corners.map(([x]) => x)));
        const maxX = Math.min(x2, Math.max(...corners.map(([x]) => x)));
        const minY = Math.max(y1, Math.min(...corners.map(([, y]) => y)));
        const maxY = Math.min(y2, Math.max(...corners.map(([, y]) => y)));
        return {
          page: pageNumber,
          x: (minX - x1) / (x2 - x1),
          y: (y2 - maxY) / (y2 - y1),
          width: (maxX - minX) / (x2 - x1),
          height: (maxY - minY) / (y2 - y1),
        };
      });
    onSelection(
      {
        paperId,
        fileId: file.paper_file_id,
        version: file.version_no,
        page: pageNumber,
        hasText: file.has_text_layer,
      },
      selection.toString(),
      rects,
    );
  }
  return (
    <>
      {Boolean(error) && (
        <ErrorBox error={error} retry={() => setReload((value) => value + 1)} />
      )}
      <div
        className="pdf-sheet"
        data-loading={rendering}
        onMouseUp={captureSelection}
      >
        <canvas key={`canvas:${pageNumber}:${scale}`} ref={canvas} />
        <div
          key={`text:${pageNumber}:${scale}`}
          ref={layer}
          className="textLayer"
        />
        <div className="source-highlight-layer" aria-hidden="true">
          {highlights.map((rect, index) => (
            <span
              key={index}
              style={{
                left: rect.x,
                top: rect.y,
                width: rect.width,
                height: rect.height,
              }}
            />
          ))}
        </div>
        {rendering && <div className="pdf-loading">正在渲染原文…</div>}
      </div>
    </>
  );
}
