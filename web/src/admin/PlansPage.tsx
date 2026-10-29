// 后台套餐配置：档位/月费/按单位含额与超额单价（upsert 即时生效，调价不发版）。
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AdminPageHeader, AdminState } from './AdminLayout'
import {
  AdminApiError,
  type AdminAuth,
  type AdminPlan,
  fetchPlans,
  putPlan,
} from './api'
import { formatMicro } from '../console/api'

interface QuotaDraft {
  unit: string
  included: string
  overageYuan: string
}

interface PlanDraft {
  code: string
  name: string
  monthlyYuan: string
  isActive: boolean
  quotas: QuotaDraft[]
}

const EMPTY_DRAFT: PlanDraft = {
  code: '',
  name: '',
  monthlyYuan: '',
  isActive: true,
  quotas: [
    { unit: 'line', included: '0', overageYuan: '0' },
    { unit: 'call', included: '0', overageYuan: '0' },
  ],
}

function yuanToMicro(raw: string): number {
  const value = Number.parseFloat(raw || '0')
  if (!Number.isFinite(value) || value < 0) return 0
  return Math.round(value * 1_000_000)
}

function draftFromPlan(plan: AdminPlan): PlanDraft {
  return {
    code: plan.code,
    name: plan.name,
    monthlyYuan: String(plan.monthly_price_micro / 1_000_000),
    isActive: plan.is_active,
    quotas: plan.quotas.length
      ? plan.quotas.map((quota) => ({
          unit: quota.unit,
          included: String(quota.included_quantity),
          overageYuan: String(quota.overage_unit_price_micro / 1_000_000),
        }))
      : EMPTY_DRAFT.quotas,
  }
}

export function PlansPage({ auth }: { auth: AdminAuth }) {
  const { t } = useTranslation()
  const [plans, setPlans] = useState<AdminPlan[] | null>(null)
  const [error, setError] = useState<{ status?: number; message: string; detail?: string } | null>(
    null,
  )
  const [draft, setDraft] = useState<PlanDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    setPlans(null)
    try {
      const listing = await fetchPlans(auth)
      setPlans(listing.plans)
    } catch (err) {
      setError(err as AdminApiError)
    }
  }, [auth])

  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    if (!draft.code.trim() || !draft.name.trim()) return
    setSaving(true)
    setNotice(null)
    try {
      await putPlan(auth, draft.code.trim(), {
        name: draft.name.trim(),
        monthly_price_micro: yuanToMicro(draft.monthlyYuan),
        is_active: draft.isActive,
        quotas: draft.quotas
          .filter((quota) => quota.unit.trim())
          .map((quota) => ({
            unit: quota.unit.trim(),
            included_quantity: Math.max(0, Number.parseInt(quota.included || '0', 10) || 0),
            overage_unit_price_micro: yuanToMicro(quota.overageYuan),
          })),
      })
      setNotice(t('admin.plans.savedNotice'))
      await load()
    } catch (err) {
      setError(err as AdminApiError)
    } finally {
      setSaving(false)
    }
  }

  const updateQuota = (index: number, patch: Partial<QuotaDraft>) => {
    setDraft((current) => ({
      ...current,
      quotas: current.quotas.map((quota, i) => (i === index ? { ...quota, ...patch } : quota)),
    }))
  }

  return (
    <div>
      <AdminPageHeader
        titleKey="admin.plans.title"
        subtitleKey="admin.plans.subtitle"
        extra={
          <span className="rounded-md border border-line bg-paper px-3 py-1.5 text-[11px] text-ink-soft">
            {t('admin.plans.noDeployNote')}
          </span>
        }
      />

      <div className="mt-6 rounded-lg border border-line bg-white p-5" data-testid="plan-editor">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-base font-semibold text-ink">
            {t('admin.plans.editorTitle')}
          </h2>
          <button
            type="button"
            onClick={() => setDraft(EMPTY_DRAFT)}
            className="text-xs text-ink-soft underline-offset-2 hover:underline"
          >
            {t('admin.plans.newDraft')}
          </button>
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-4">
          <label className="text-xs text-ink-soft">
            {t('admin.plans.codeLabel')}
            <input
              data-testid="plan-code"
              value={draft.code}
              onChange={(event) => setDraft({ ...draft, code: event.target.value })}
              className="mt-1 block w-full rounded border border-line-strong bg-white px-2 py-1.5 font-mono text-sm"
            />
          </label>
          <label className="text-xs text-ink-soft">
            {t('admin.plans.nameLabel')}
            <input
              data-testid="plan-name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              className="mt-1 block w-full rounded border border-line-strong bg-white px-2 py-1.5 text-sm"
            />
          </label>
          <label className="text-xs text-ink-soft">
            {t('admin.plans.monthlyLabel')}
            <input
              data-testid="plan-monthly"
              type="number"
              min="0"
              step="0.01"
              value={draft.monthlyYuan}
              onChange={(event) => setDraft({ ...draft, monthlyYuan: event.target.value })}
              className="mt-1 block w-full rounded border border-line-strong bg-white px-2 py-1.5 text-sm"
            />
          </label>
          <label className="mt-5 flex items-center gap-2 text-xs text-ink-soft">
            <input
              type="checkbox"
              data-testid="plan-active"
              checked={draft.isActive}
              onChange={(event) => setDraft({ ...draft, isActive: event.target.checked })}
            />
            {t('admin.plans.activeLabel')}
          </label>
        </div>

        <h3 className="mt-4 text-xs font-medium text-ink-soft">{t('admin.plans.quotasTitle')}</h3>
        <div className="mt-2 space-y-2">
          {draft.quotas.map((quota, index) => (
            <div key={`${quota.unit}:${index}`} className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-ink-soft">
                {t('console.common.unit')}
                <input
                  value={quota.unit}
                  onChange={(event) => updateQuota(index, { unit: event.target.value })}
                  className="mt-1 block w-28 rounded border border-line-strong bg-white px-2 py-1.5 font-mono text-sm"
                />
              </label>
              <label className="text-xs text-ink-soft">
                {t('admin.plans.includedLabel')}
                <input
                  data-testid={`plan-quota-included-${index}`}
                  type="number"
                  min="0"
                  value={quota.included}
                  onChange={(event) => updateQuota(index, { included: event.target.value })}
                  className="mt-1 block w-36 rounded border border-line-strong bg-white px-2 py-1.5 text-sm"
                />
              </label>
              <label className="text-xs text-ink-soft">
                {t('admin.plans.overageLabel')}
                <input
                  data-testid={`plan-quota-overage-${index}`}
                  type="number"
                  min="0"
                  step="0.0001"
                  value={quota.overageYuan}
                  onChange={(event) => updateQuota(index, { overageYuan: event.target.value })}
                  className="mt-1 block w-36 rounded border border-line-strong bg-white px-2 py-1.5 text-sm"
                />
              </label>
              <button
                type="button"
                onClick={() =>
                  setDraft((current) => ({
                    ...current,
                    quotas: current.quotas.filter((_, i) => i !== index),
                  }))
                }
                className="pb-2 text-xs text-seal underline-offset-2 hover:underline"
              >
                {t('admin.plans.removeQuota')}
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() =>
            setDraft((current) => ({
              ...current,
              quotas: [...current.quotas, { unit: '', included: '0', overageYuan: '0' }],
            }))
          }
          className="mt-2 text-xs text-field underline-offset-2 hover:underline"
        >
          {t('admin.plans.addQuota')}
        </button>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            data-testid="plan-save"
            disabled={saving || !draft.code.trim() || !draft.name.trim()}
            onClick={() => void save()}
            className="rounded-md bg-field px-4 py-2 text-sm text-white transition-colors hover:bg-field-deep disabled:opacity-50"
          >
            {saving ? t('admin.plans.saving') : t('admin.plans.save')}
          </button>
          {notice && (
            <span className="text-xs text-field" data-testid="plan-notice">
              {notice}
            </span>
          )}
        </div>
      </div>

      <AdminState
        loading={plans === null}
        error={error}
        empty={(plans ?? []).length === 0}
        emptyKey="admin.plans.empty"
        onRetry={() => void load()}
      >
        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-white">
          <table className="w-full text-sm">
            <thead className="bg-paper text-left text-xs text-ink-soft">
              <tr>
                <th className="px-4 py-2.5 font-medium">{t('admin.plans.colCode')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.plans.colName')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.plans.colMonthly')}</th>
                <th className="px-4 py-2.5 font-medium">{t('admin.plans.colQuotas')}</th>
                <th className="px-4 py-2.5 text-right font-medium">
                  {t('admin.plans.colActions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {(plans ?? []).map((plan) => (
                <tr key={plan.code} className="border-t border-line" data-testid="plan-row">
                  <td className="px-4 py-2.5 font-mono text-xs">{plan.code}</td>
                  <td className="px-4 py-2.5">
                    {plan.name}
                    {!plan.is_active && (
                      <span className="ml-2 rounded-full border border-line-strong px-2 py-0.5 text-[10px] text-ink-soft">
                        {t('admin.plans.inactive')}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{plan.monthly_price_yuan}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-soft">
                    {plan.quotas
                      .map(
                        (quota) =>
                          `${quota.unit}: ${quota.included_quantity.toLocaleString()} / ${formatMicro(quota.overage_unit_price_micro)}`,
                      )
                      .join(' · ') || '—'}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button
                      type="button"
                      data-testid={`plan-edit-${plan.code}`}
                      onClick={() => setDraft(draftFromPlan(plan))}
                      className="text-xs text-field underline-offset-2 hover:underline"
                    >
                      {t('admin.plans.edit')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </AdminState>
    </div>
  )
}

export default PlansPage