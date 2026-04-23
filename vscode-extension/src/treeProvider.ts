import * as vscode from 'vscode';

export interface ApexRisk {
    severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
    branch: string;
    claim: string;
    file: string;
}

export class ApexResultsProvider implements vscode.TreeDataProvider<ApexRiskItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<ApexRiskItem | undefined | void>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    
    private risks: ApexRisk[] = [];

    setResults(risks: ApexRisk[]) {
        this.risks = risks;
        this.refresh();
    }

    clear() {
        this.risks = [];
        this.refresh();
    }

    refresh() {
        this._onDidChangeTreeData.fire();
    }

    getTreeItem(element: ApexRiskItem): vscode.TreeItem {
        return element;
    }

    getChildren(element?: ApexRiskItem): ApexRiskItem[] {
        if (!element) {
            // Root level: group by severity
            const groups = this.groupBySeverity();
            return Object.entries(groups).map(([severity, items]) => 
                new ApexRiskItem(severity, items.length, severity as any, undefined)
            );
        }
        // Child level: individual risks
        if (element.collapsibleState === vscode.TreeItemCollapsibleState.Collapsed ||
            element.collapsibleState === vscode.TreeItemCollapsibleState.Expanded) {
            const group = this.risks.filter(r => r.severity === element.severity);
            return group.map(r => new ApexRiskItem(r.claim, 0, r.severity, r));
        }
        return [];
    }

    private groupBySeverity(): Record<string, ApexRisk[]> {
        const groups: Record<string, ApexRisk[]> = {};
        for (const risk of this.risks) {
            groups[risk.severity] = groups[risk.severity] || [];
            groups[risk.severity].push(risk);
        }
        return groups;
    }
}

class ApexRiskItem extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly count: number,
        public readonly severity: string,
        public readonly risk: ApexRisk | undefined
    ) {
        super(
            count > 0 ? `${label} (${count})` : label,
            count > 0 ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
        );
        
        const icons: Record<string, string> = {
            critical: '$(error)',
            high: '$(warning)',
            medium: '$(info)',
            low: '$(check)',
            info: '$(symbol-info)'
        };
        
        if (count > 0) {
            this.iconPath = new vscode.ThemeIcon('folder');
        } else {
            this.iconPath = new vscode.ThemeIcon(icons[severity] ? 'circle-filled' : 'circle-outline');
        }
        
        if (risk) {
            this.tooltip = `${risk.branch}: ${risk.claim}`;
            this.command = {
                command: 'apex.openFile',
                title: 'Open File',
                arguments: [risk.file]
            };
        }
    }
}
