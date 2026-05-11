import { apiUrl } from "@/lib/api";
import { invalidateClientCache, withClientCache } from "@/lib/client-cache";

const SKILLS_CACHE_PREFIX = "skills:";
const SKILL_TAGS_CACHE_KEY = `${SKILLS_CACHE_PREFIX}tags`;

export interface SkillInfo {
  name: string;
  description: string;
  tags: string[];
}

export interface SkillDetail extends SkillInfo {
  content: string;
}

export interface CreateSkillPayload {
  name: string;
  description: string;
  content: string;
  tags?: string[];
}

export interface UpdateSkillPayload {
  description?: string;
  content?: string;
  rename_to?: string;
  tags?: string[];
}

function normalizeTags(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    const tag = String(item ?? "").trim().toLowerCase();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    out.push(tag);
  }
  return out;
}

async function asJson(response: Response) {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function listSkills(options?: {
  force?: boolean;
}): Promise<SkillInfo[]> {
  return withClientCache<SkillInfo[]>(
    `${SKILLS_CACHE_PREFIX}list`,
    async () => {
      const response = await fetch(apiUrl("/api/v1/skills/list"), {
        cache: "no-store",
      });
      const data = await asJson(response);
      const items = Array.isArray(data?.skills) ? data.skills : [];
      return items.map(
        (item: {
          name?: unknown;
          description?: unknown;
          tags?: unknown;
        }) => ({
          name: String(item?.name ?? ""),
          description: String(item?.description ?? ""),
          tags: normalizeTags(item?.tags),
        }),
      );
    },
    { force: options?.force },
  );
}

export async function getSkill(name: string): Promise<SkillDetail> {
  const response = await fetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      cache: "no-store",
    },
  );
  const data = await asJson(response);
  return {
    name: String(data?.name ?? name),
    description: String(data?.description ?? ""),
    content: String(data?.content ?? ""),
    tags: normalizeTags(data?.tags),
  };
}

export async function createSkill(
  payload: CreateSkillPayload,
): Promise<SkillInfo> {
  const response = await fetch(apiUrl("/api/v1/skills/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: payload.name,
      description: payload.description,
      content: payload.content,
      tags: payload.tags ?? [],
    }),
  });
  const data = await asJson(response);
  invalidateSkillsCache();
  return {
    name: String(data?.name ?? payload.name),
    description: String(data?.description ?? payload.description ?? ""),
    tags: normalizeTags(data?.tags ?? payload.tags),
  };
}

export async function updateSkill(
  name: string,
  payload: UpdateSkillPayload,
): Promise<SkillInfo> {
  const response = await fetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const data = await asJson(response);
  invalidateSkillsCache();
  return {
    name: String(data?.name ?? name),
    description: String(data?.description ?? ""),
    tags: normalizeTags(data?.tags),
  };
}

export async function deleteSkill(name: string): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/v1/skills/${encodeURIComponent(name)}`),
    {
      method: "DELETE",
    },
  );
  await asJson(response);
  invalidateSkillsCache();
}

export async function listSkillTags(options?: {
  force?: boolean;
}): Promise<string[]> {
  return withClientCache<string[]>(
    SKILL_TAGS_CACHE_KEY,
    async () => {
      const response = await fetch(apiUrl("/api/v1/skills/tags/list"), {
        cache: "no-store",
      });
      const data = await asJson(response);
      return normalizeTags(data?.tags);
    },
    { force: options?.force },
  );
}

export async function createSkillTag(name: string): Promise<string> {
  const response = await fetch(apiUrl("/api/v1/skills/tags/create"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await asJson(response);
  invalidateSkillsCache();
  return String(data?.name ?? name);
}

export async function renameSkillTag(
  oldName: string,
  newName: string,
): Promise<string> {
  const response = await fetch(
    apiUrl(`/api/v1/skills/tags/${encodeURIComponent(oldName)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rename_to: newName }),
    },
  );
  const data = await asJson(response);
  invalidateSkillsCache();
  return String(data?.name ?? newName);
}

export async function deleteSkillTag(name: string): Promise<void> {
  const response = await fetch(
    apiUrl(`/api/v1/skills/tags/${encodeURIComponent(name)}`),
    {
      method: "DELETE",
    },
  );
  await asJson(response);
  invalidateSkillsCache();
}

export function invalidateSkillsCache() {
  invalidateClientCache(SKILLS_CACHE_PREFIX);
}
