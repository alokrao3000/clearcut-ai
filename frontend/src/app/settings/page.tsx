"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronLeft, UserPlus } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useCreateOrgUser,
  useMe,
  useOrgUsers,
  useUpdateOrgUser,
} from "@/hooks/use-clearcut";
import { relativeTime } from "@/lib/format";
import { ROLE_HINT, ROLE_LABEL } from "@/lib/labels";
import { ROLES, type Role } from "@/lib/types";

export default function SettingsPage() {
  const { data: me } = useMe();
  const { data: users, isLoading } = useOrgUsers();
  const canManage = me ? ["owner", "admin"].includes(me.user.role) : false;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Link
          href="/"
          className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" /> All projects
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          {me?.organization.name ?? "Organization"}
        </h1>
        <p className="text-sm text-muted-foreground">
          People in this organization. Everything in ClearCut belongs to it, and nobody
          outside it can see any of it.
        </p>
      </div>

      {canManage && <AddPerson />}

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="bg-muted/60 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Person</th>
                <th className="px-3 py-2 text-left font-medium">Role</th>
                <th className="px-3 py-2 text-left font-medium">Last signed in</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(users ?? []).map((user) => (
                <PersonRow
                  key={user.id}
                  user={user}
                  canManage={canManage}
                  isSelf={user.id === me?.user.id}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Changing someone&apos;s role or disabling them ends their sessions immediately, rather
        than when their token happens to expire.
      </p>
    </div>
  );
}

function PersonRow({
  user,
  canManage,
  isSelf,
}: {
  user: { id: string; email: string; name: string; role: Role; is_active: boolean; last_login_at: string | null };
  canManage: boolean;
  isSelf: boolean;
}) {
  const update = useUpdateOrgUser();

  return (
    <tr className={user.is_active ? undefined : "text-muted-foreground"}>
      <td className="px-3 py-2">
        <div className="font-medium">
          {user.name}
          {isSelf && <span className="ml-2 text-xs font-normal text-muted-foreground">you</span>}
        </div>
        <div className="text-xs text-muted-foreground">{user.email}</div>
      </td>
      <td className="px-3 py-2">
        {canManage && !isSelf ? (
          <Select
            value={user.role}
            onValueChange={(role) =>
              update.mutate(
                { id: user.id, body: { role: role as Role } },
                { onSuccess: () => toast.success(`${user.name} is now ${ROLE_LABEL[role]}`) },
              )
            }
          >
            <SelectTrigger className="h-8 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map((role) => (
                <SelectItem key={role} value={role}>
                  {ROLE_LABEL[role]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Badge variant="secondary">{ROLE_LABEL[user.role]}</Badge>
        )}
      </td>
      <td className="px-3 py-2 text-muted-foreground">
        {user.last_login_at ? relativeTime(user.last_login_at) : "Never"}
      </td>
      <td className="px-3 py-2">
        {canManage && !isSelf ? (
          <Button
            size="sm"
            variant="ghost"
            className="text-muted-foreground"
            onClick={() =>
              update.mutate({ id: user.id, body: { is_active: !user.is_active } })
            }
          >
            {user.is_active ? "Disable" : "Re-enable"}
          </Button>
        ) : (
          <Badge variant={user.is_active ? "outline" : "muted"}>
            {user.is_active ? "Active" : "Disabled"}
          </Badge>
        )}
      </td>
    </tr>
  );
}

function AddPerson() {
  const create = useCreateOrgUser();
  const [role, setRole] = React.useState<Role>("member");

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    create.mutate(
      {
        email: String(data.get("email")),
        name: String(data.get("name")),
        password: String(data.get("password")),
        role,
      },
      {
        onSuccess: (user) => {
          toast.success(`Added ${user.email}`);
          form.reset();
        },
      },
    );
  };

  return (
    <Card>
      <CardContent className="p-4">
        <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
          <div className="flex min-w-40 flex-1 flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input id="name" name="name" required />
          </div>
          <div className="flex min-w-48 flex-1 flex-col gap-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" name="email" type="email" required />
          </div>
          <div className="flex min-w-48 flex-1 flex-col gap-1.5">
            <Label htmlFor="password">Temporary password</Label>
            <Input id="password" name="password" type="password" required minLength={12} />
          </div>
          <div className="flex w-40 flex-col gap-1.5">
            <Label htmlFor="role">Role</Label>
            <Select value={role} onValueChange={(v) => setRole(v as Role)}>
              <SelectTrigger id="role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={create.isPending}>
            <UserPlus /> Add
          </Button>
        </form>
        <p className="mt-2 text-xs text-muted-foreground">{ROLE_HINT[role]}</p>
      </CardContent>
    </Card>
  );
}
