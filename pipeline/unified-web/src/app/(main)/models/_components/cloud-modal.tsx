"use client";

import * as React from "react";

import { Loader2Icon, SaveIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

import { type CloudModelInfo, studioApi } from "./types";

export function CloudProviderModal({
  open,
  onOpenChange,
  editing,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing: CloudModelInfo | null;
  onSaved: () => Promise<void>;
}) {
  const [id, setId] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [alias, setAlias] = React.useState("");
  const [apiBase, setApiBase] = React.useState("");
  const [targetModel, setTargetModel] = React.useState("");
  const [apiKeyEnv, setApiKeyEnv] = React.useState("");
  const [apiKey, setApiKey] = React.useState("");
  const [supportsVision, setSupportsVision] = React.useState(false);
  const [enabled, setEnabled] = React.useState(true);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (editing) {
      setId(editing.id);
      setLabel(editing.label);
      setAlias(editing.alias);
      setApiBase(editing.api_base);
      setTargetModel(editing.target_model);
      setApiKeyEnv(editing.api_key_env);
      setApiKey("");
      setSupportsVision(editing.supports_vision);
      setEnabled(editing.enabled);
    } else {
      setId("");
      setLabel("");
      setAlias("");
      setApiBase("https://api.openai.com/v1");
      setTargetModel("openai/gpt-5");
      setApiKeyEnv("");
      setApiKey("");
      setSupportsVision(false);
      setEnabled(true);
    }
  }, [editing, open]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await studioApi<{ ok: boolean; error?: string }>("/cloud/save", {
        method: "POST",
        body: {
          id: id || alias,
          label: label || id || alias,
          alias: alias || id,
          api_base: apiBase,
          target_model: targetModel,
          api_key_env: apiKeyEnv,
          api_key: apiKey,
          supports_vision: supportsVision,
          enabled,
        },
      });
      if (!res.ok) throw new Error(res.error || "Failed to save cloud provider");
      toast.success("บันทึก Cloud Provider และซิงก์ LiteLLM เรียบร้อย");
      onOpenChange(false);
      await onSaved();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `แก้ไข ${editing.label}` : "เพิ่ม Cloud Provider"}</DialogTitle>
          <DialogDescription>
            เชื่อมต่อ Cloud API (NIM, OpenRouter, OpenAI, Custom Endpoint) เข้า LiteLLM Router (:4000)
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(e) => void save(e)} className="grid gap-3 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs">Provider ID / Alias</Label>
              <Input
                value={alias}
                onChange={(e) => {
                  setAlias(e.target.value);
                  if (!editing) setId(e.target.value);
                }}
                placeholder="openrouter-claude"
                required
              />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">Display Label</Label>
              <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="OpenRouter Claude" />
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs">LiteLLM Target Model</Label>
            <Input
              value={targetModel}
              onChange={(e) => setTargetModel(e.target.value)}
              placeholder="openrouter/anthropic/claude-sonnet-4"
              className="font-mono text-xs"
              required
            />
          </div>

          <div className="grid gap-1.5">
            <Label className="text-xs">API Base URL (เว้นว่างถ้าใช้ default ของ provider)</Label>
            <Input
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="https://integrate.api.nvidia.com/v1"
              className="font-mono text-xs"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label className="text-xs">Env Var Name (เช่น NVIDIA_API_KEY)</Label>
              <Input
                value={apiKeyEnv}
                onChange={(e) => setApiKeyEnv(e.target.value)}
                placeholder="OPENROUTER_API_KEY"
                className="font-mono text-xs"
              />
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">หรือใส่ API Key ตรง (ถ้าไม่ใช้ env)</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg border p-2.5">
            <span className="text-xs">รองรับภาพ (Vision)</span>
            <Switch checked={supportsVision} onCheckedChange={setSupportsVision} />
          </div>

          <div className="flex items-center justify-between rounded-lg border p-2.5">
            <span className="text-xs">เปิดใช้งานใน LiteLLM Router</span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              ยกเลิก
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
              บันทึก & ซิงก์ LiteLLM
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
