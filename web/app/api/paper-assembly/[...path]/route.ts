import { NextRequest, NextResponse } from "next/server";
import { paperAssemblyService } from "@/lib/paper-assembly-agent/service";

type RouteContext = { params: Promise<{ path?: string[] }> };
type Payload = Record<string, unknown>;

function json(payload: unknown, status = 200) {
  return NextResponse.json(payload, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

async function readJson(request: NextRequest): Promise<Payload> {
  const text = await request.text();
  if (!text.trim()) return {};
  return JSON.parse(text) as Payload;
}

function userIdFor(request: NextRequest): string {
  return request.nextUrl.searchParams.get("user_id") || paperAssemblyService.defaultUserId;
}

async function handlePaperAssembly(request: NextRequest, context: RouteContext) {
  const params = await context.params;
  const segments = params.path || [];
  const route = `/${segments.join("/")}`;
  const userId = userIdFor(request);

  try {
    if (request.method === "GET" && route === "/health") return json(paperAssemblyService.health());
    if (request.method === "GET" && route === "/modules") return json(paperAssemblyService.modules());
    if (request.method === "GET" && route === "/subjects") return json(paperAssemblyService.subjects());
    if (request.method === "GET" && route === "/paper/question-types") return json(paperAssemblyService.questionTypes());
    if (request.method === "GET" && route === "/papers/original") return json(paperAssemblyService.originalPapers());
    if (request.method === "GET" && route === "/uploads") return json(paperAssemblyService.uploads());
    if (request.method === "GET" && route === "/conversion/status") return json(paperAssemblyService.conversionStatus());
    if (request.method === "GET" && route === "/wrong-questions") return json(paperAssemblyService.wrongQuestions(userId));
    if (request.method === "GET" && route === "/wrong-questions/summary") {
      return json(paperAssemblyService.wrongQuestionSummary(userId));
    }
    if (request.method === "GET" && route === "/annotations") return json(paperAssemblyService.annotations(userId));
    if (request.method === "GET" && route === "/annotations/items") return json(paperAssemblyService.annotationItems(userId));

    if (request.method === "POST" && route === "/uploads") {
      const formData = await request.formData();
      const file = formData.get("file");
      if (!(file instanceof File)) return json({ error: "No file field found" }, 400);
      return json(
        paperAssemblyService.saveUploadedMaterial({
          filename: file.name,
          mimeType: file.type,
          buffer: Buffer.from(await file.arrayBuffer()),
        }),
      );
    }

    if (request.method === "PATCH" && route === "/uploads") {
      const item = paperAssemblyService.updateUploadedMaterial(await readJson(request));
      return item ? json({ item }) : json({ error: "Upload not found" }, 404);
    }

    if (request.method === "DELETE" && route === "/uploads") {
      const deleted = paperAssemblyService.deleteUploadedMaterial(await readJson(request));
      return deleted ? json({ deleted }) : json({ error: "Upload not found" }, 404);
    }

    if (request.method === "POST" && route === "/conversion/system-exams") {
      return json(paperAssemblyService.convertSystemExams());
    }

    if (request.method === "POST" && route === "/paper/assemble") {
      return json(paperAssemblyService.assemble(await readJson(request), userId));
    }

    if (request.method === "POST" && route === "/wrong-questions/add") {
      const result = paperAssemblyService.addWrongQuestion(await readJson(request), userId);
      return result ? json(result) : json({ error: "Question not found" }, 404);
    }

    const reasonMatch = route.match(/^\/wrong-questions\/([^/]+)\/reason$/);
    if (request.method === "POST" && reasonMatch) {
      const item = paperAssemblyService.updateWrongReason(
        decodeURIComponent(reasonMatch[1]),
        await readJson(request),
        userId,
      );
      return item ? json({ item }) : json({ error: "Wrong question not found" }, 404);
    }

    const retryMatch = route.match(/^\/wrong-questions\/([^/]+)\/retry$/);
    if (request.method === "POST" && retryMatch) {
      const item = paperAssemblyService.recordRetry(
        decodeURIComponent(retryMatch[1]),
        await readJson(request),
        userId,
      );
      return item ? json({ item }) : json({ error: "Wrong question not found" }, 404);
    }

    const annotationMatch = route.match(/^\/questions\/([^/]+)\/annotation$/);
    if (request.method === "POST" && annotationMatch) {
      return json(
        paperAssemblyService.updateAnnotation(
          decodeURIComponent(annotationMatch[1]),
          await readJson(request),
          userId,
        ),
      );
    }

    return json({ error: "API route not found" }, 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return json({ error: message }, 500);
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const GET = handlePaperAssembly;
export const POST = handlePaperAssembly;
export const PATCH = handlePaperAssembly;
export const DELETE = handlePaperAssembly;
