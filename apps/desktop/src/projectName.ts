export interface ProjectNameSource {
  key: string;
  name: string;
}

const HAN_CHARACTER = /\p{Script=Han}/u;

export function projectDisplayName(project: ProjectNameSource): string {
  const candidates = [project.name.trim(), project.key.trim()].filter(Boolean);
  return candidates.find((candidate) => HAN_CHARACTER.test(candidate))
    ?? candidates[0]
    ?? "未命名需求";
}
