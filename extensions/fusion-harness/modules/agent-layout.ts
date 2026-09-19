export interface AgentGridLayout {
	stacked: boolean;
	columnWidth: number;
	count: number;
	gutterWidth: number;
}

export function computeAgentGridLayout(
	width: number,
	countInput: number,
	gutterWidth = 3,
	minimumColumnWidth = 34,
): AgentGridLayout {
	const count = Math.max(1, Math.min(5, Math.trunc(countInput) || 1));
	const safeWidth = Math.max(1, Math.trunc(width) || 1);
	const safeGutter = Math.max(0, Math.trunc(gutterWidth) || 0);
	const columnWidth = Math.floor((safeWidth - safeGutter * (count - 1)) / count);
	return {
		stacked: count === 1 || columnWidth < minimumColumnWidth,
		columnWidth: Math.max(1, columnWidth),
		count,
		gutterWidth: safeGutter,
	};
}
