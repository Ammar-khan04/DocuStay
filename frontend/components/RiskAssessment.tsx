
import React from 'react';
import { Card } from './UI';

interface RiskAssessmentProps {
  data: {
    classification: {
      riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
      riskScore: number;
      stayType: string;
    };
    limits: {
      platformRenewalCycleDays?: number;
      legalThresholdDays?: number | null;
      daysUntilRisk: number;
      maxSafeStayDays?: number;
    };
    riskFactors: Array<{
      factor: string;
      severity: string;
      message: string;
    }>;
  };
  compact?: boolean;
}

export const RiskAssessment: React.FC<RiskAssessmentProps> = ({ data, compact }) => {
  const colors = {
    LOW: 'text-green-400 bg-green-500/10 border-green-500/20',
    MEDIUM: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
    HIGH: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
    CRITICAL: 'text-red-500 bg-red-500/10 border-red-500/20'
  };

  if (compact) {
    return (
      <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border ${colors[data.classification.riskLevel]}`}>
        {data.classification.riskLevel} Risk
      </span>
    );
  }

  return (
    <Card className="p-6 border-l-4 border-blue-500">
      <div className="flex justify-between items-start mb-8">
        <div>
          <h4 className="text-sm font-bold text-gray-500 uppercase tracking-widest mb-1">Stay Classification</h4>
          <p className="text-xl font-extrabold text-white">{(data.classification.stayType || '').replace('_', ' ')}</p>
        </div>
        <div className="text-right">
          <h4 className="text-sm font-bold text-gray-500 uppercase tracking-widest mb-1">Risk Score</h4>
          <p className={`text-2xl font-black ${data.classification.riskScore > 40 ? 'text-orange-500' : 'text-green-500'}`}>{data.classification.riskScore}/100</p>
        </div>
      </div>

      <div className="space-y-6">
        <div>
          {(() => {
            const cycle = data.limits.platformRenewalCycleDays ?? data.limits.maxSafeStayDays ?? 14;
            const elapsed = cycle - data.limits.daysUntilRisk;
            return (
              <>
                <div className="flex justify-between text-xs font-bold mb-2">
                  <span className="text-gray-400 uppercase">Renewal Cycle Progress</span>
                  <span className="text-white">{elapsed} / {cycle} Days</span>
                </div>
                <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all duration-1000 ${data.limits.daysUntilRisk < 5 ? 'bg-red-500' : 'bg-blue-500'}`}
                    style={{ width: `${(elapsed / cycle) * 100}%` }}
                  ></div>
                </div>
                {data.limits.legalThresholdDays != null && (
                  <p className="text-[10px] text-gray-500 mt-1">
                    Legal threshold: {data.limits.legalThresholdDays} days &middot; Platform renewal cycle: {cycle} days
                  </p>
                )}
              </>
            );
          })()}
        </div>

        <div className="space-y-3">
          <h4 className="text-[10px] font-black text-gray-600 uppercase tracking-[0.2em]">Risk Factors</h4>
          {data.riskFactors.length === 0 ? (
            <div className="flex items-center gap-2 text-green-400 text-sm">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
              No elevated risk factors detected.
            </div>
          ) : (
            data.riskFactors.map((rf, i) => (
              <div key={i} className="flex gap-3 items-start p-3 rounded-xl bg-white/5 border border-white/5">
                <div className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${rf.severity === 'CRITICAL' ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]' : 'bg-orange-500'}`}></div>
                <p className="text-xs text-gray-300 leading-relaxed">{rf.message}</p>
              </div>
            ))
          )}
        </div>
      </div>
    </Card>
  );
};
