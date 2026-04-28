import { z } from 'zod';

export const AgentDefSchema = z.object({
  name: z.string().min(1, 'Agent名不能为空'),
  runtime_id: z.string().default('auto'),
  model: z.string().optional(),
  role: z.string().optional(),
  prompt: z.string().optional(),
});

export const QualityGateSchema = z.object({
  name: z.string().min(1, 'Gate名不能为空'),
  type: z.enum(['command', 'threshold']),
  command: z.string().optional(),
  threshold: z.string().optional(),
  required: z.boolean().default(true),
});

export const LoopbackSchema = z.object({
  on: z.string().min(1),
  to: z.string().min(1),
  max_retries: z.number().int().min(1).max(10).default(3),
});

export const StageSchema = z.object({
  id: z.string().min(1, 'Stage ID不能为空'),
  name: z.string().min(1, 'Stage名称不能为空'),
  agents: z.array(z.string()).default([]),
  agent_defs: z.array(AgentDefSchema).optional(),
  input: z.string().optional(),
  output: z.record(z.string(), z.string()).optional(),
  loopback: LoopbackSchema.optional(),
  quality_gates: z.array(QualityGateSchema).optional(),
  is_parallel: z.boolean().default(false),
});

export const PipelineConfigSchema = z.object({
  name: z.string().min(1, 'Pipeline名称不能为空'),
  description: z.string().default(''),
  version: z.string().default('1.0'),
  stages: z.array(StageSchema).min(1, '至少需要一个Stage'),
  quality_gates: z.array(QualityGateSchema).optional(),
});

export type AgentDef = z.infer<typeof AgentDefSchema>;
export type QualityGate = z.infer<typeof QualityGateSchema>;
export type Loopback = z.infer<typeof LoopbackSchema>;
export type StageConfig = z.infer<typeof StageSchema>;
export type PipelineConfig = z.infer<typeof PipelineConfigSchema>;
