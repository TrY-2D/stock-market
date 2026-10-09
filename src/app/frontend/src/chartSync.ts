import type {
  IChartApi,
  ISeriesApi,
  Time,
  LogicalRange,
  MouseEventParams,
  SeriesType,
} from 'lightweight-charts';

export interface SyncedChartInstance {
  id: string;
  chart: IChartApi;
  primarySeries: ISeriesApi<SeriesType>;
  dataMap: Map<number, number>;
}

class ChartSyncManager {
  private instances = new Map<string, SyncedChartInstance>();
  private isSyncingRange = false;
  private isSyncingCrosshair = false;
  public enabled = true;

  public setEnabled(enabled: boolean) {
    this.enabled = enabled;
    if (!enabled) {
      this.clearAllCrosshairs();
    }
  }

  public register(instance: SyncedChartInstance) {
    this.instances.set(instance.id, instance);
  }

  public updateDataMap(id: string, dataMap: Map<number, number>) {
    const inst = this.instances.get(id);
    if (inst) {
      inst.dataMap = dataMap;
    }
  }

  public unregister(id: string) {
    this.instances.delete(id);
  }

  public syncLogicalRange(sourceId: string, range: LogicalRange | null) {
    if (!this.enabled || this.isSyncingRange || !range) return;
    this.isSyncingRange = true;
    try {
      this.instances.forEach((inst, id) => {
        if (id !== sourceId && inst.chart) {
          try {
            inst.chart.timeScale().setVisibleLogicalRange(range);
          } catch (err) {
            // chart disposed or unmounted
          }
        }
      });
    } finally {
      setTimeout(() => {
        this.isSyncingRange = false;
      }, 0);
    }
  }

  public syncCrosshair(sourceId: string, param: MouseEventParams<Time>) {
    if (!this.enabled || this.isSyncingCrosshair) return;
    this.isSyncingCrosshair = true;
    try {
      const time = param.time as unknown as number;
      if (!time || !param.point) {
        this.instances.forEach((inst, id) => {
          if (id !== sourceId && inst.chart) {
            try {
              inst.chart.clearCrosshairPosition();
            } catch (err) {}
          }
        });
        return;
      }

      this.instances.forEach((inst, id) => {
        if (id !== sourceId && inst.chart && inst.primarySeries) {
          try {
            const val = inst.dataMap.get(time);
            if (val !== undefined && Number.isFinite(val)) {
              inst.chart.setCrosshairPosition(val, time as unknown as Time, inst.primarySeries);
            } else {
              inst.chart.clearCrosshairPosition();
            }
          } catch (err) {}
        }
      });
    } finally {
      setTimeout(() => {
        this.isSyncingCrosshair = false;
      }, 0);
    }
  }

  public clearAllCrosshairs() {
    this.instances.forEach((inst) => {
      try {
        inst.chart.clearCrosshairPosition();
      } catch (err) {}
    });
  }
}

export const chartSync = new ChartSyncManager();
